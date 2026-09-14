"""Search the index: keyword leg + meaning leg, merged with rank fusion.

Usage: python search.py "your question"
Prints the top hits with the lines around them, and which leg found each.
"""

import re
import sqlite3
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from paths import DB, EMBEDDING_MODEL, MODEL_DIR  # noqa: E402
K = 60  # rank fusion smoothing constant
TOP = 3
CONTEXT_LINES = 6
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "  # bge query instruction


STOPWORDS = {
    "a", "an", "and", "are", "at", "can", "do", "does", "for", "how", "i",
    "in", "is", "it", "my", "of", "on", "or", "our", "the", "to", "we",
    "what", "when", "where", "who", "why", "with", "you", "your",
}


def query_terms(query):
    """The searchable words of a query: lowercased, stopwords dropped."""
    return [t for t in re.findall(r"\w+", query.lower()) if t not in STOPWORDS]


def keyword_leg(db, query):
    terms = query_terms(query)
    if not terms:
        return []
    match = " OR ".join(f'"{t}"' for t in terms)
    rows = db.execute(
        "SELECT rowid FROM chunks_fts WHERE chunks_fts MATCH ? ORDER BY bm25(chunks_fts) LIMIT 10",
        (match,),
    ).fetchall()
    return [r[0] for r in rows]


def embedding_model():
    """The configured model: the pinned local dir when it's BGE-small (the
    only model fetch_model.sh pins), else fastembed downloads/caches it by name."""
    from fastembed import TextEmbedding

    if MODEL_DIR.is_dir() and EMBEDDING_MODEL == "BAAI/bge-small-en-v1.5":
        return TextEmbedding(specific_model_path=str(MODEL_DIR))
    try:  # cached copy first: the hub check alone costs ~1.3 s per hook call
        return TextEmbedding(model_name=EMBEDDING_MODEL, local_files_only=True)
    except Exception:
        return TextEmbedding(model_name=EMBEDDING_MODEL)  # first run downloads


def meaning_leg(db, query):
    try:
        from fastembed import TextEmbedding  # noqa: F401 — availability check
    except ImportError:
        return None
    rows = db.execute("SELECT id, vec FROM vectors").fetchall()
    if not rows:
        return None
    stored_model = db.execute("SELECT value FROM meta WHERE key='model'").fetchone()
    if stored_model and stored_model[0] != EMBEDDING_MODEL:
        print(f"warning: index built with {stored_model[0]!r}, config wants "
              f"{EMBEDDING_MODEL!r} — vectors are stale until build_index.py --full runs",
              file=sys.stderr)
    model = embedding_model()
    q = np.array(list(model.embed([QUERY_PREFIX + query]))[0], dtype=np.float32)
    q /= np.linalg.norm(q) or 1.0
    ids = [rowid for rowid, _ in rows]
    # stored vectors are already unit-normalized by build_index
    matrix = np.vstack([np.frombuffer(blob, dtype=np.float32) for _, blob in rows])
    top = np.argsort(-(matrix @ q))[:10]
    return [ids[i] for i in top]


def fuse(legs):
    scores, found_by = {}, {}
    for name, ids in legs.items():
        for rank, rowid in enumerate(ids):
            scores[rowid] = scores.get(rowid, 0.0) + 1.0 / (K + rank)
            found_by.setdefault(rowid, []).append(name)
    ranked = sorted(scores, key=scores.get, reverse=True)
    return ranked, found_by


def show(db, rowid, position, legs):
    file, section, start, end, text, kind = db.execute(
        "SELECT file, section, start_line, end_line, text, kind FROM chunks WHERE id=?",
        (rowid,),
    ).fetchone()
    print(f"{position}. [{file} § {section}]  legs: {'+'.join(legs)}")
    out = []
    if kind != "chunk":  # distilled and description rows have no source lines
        out = text.splitlines()
    else:
        corpus = db.execute("SELECT value FROM meta WHERE key='corpus'").fetchone()
        source = Path(corpus[0]) / file if corpus else HERE.parent / "corpus-before" / file
        if source.is_file():
            lines = source.read_text(encoding="utf-8").splitlines()
            s = max(0, start - 1 - CONTEXT_LINES)
            e = min(len(lines), end + CONTEXT_LINES)
            # context lines wear a dot; the chunk itself is bare
            out = ["· " + l for l in lines[s : start - 1]]
            out += lines[start - 1 : end]
            out += ["· " + l for l in lines[end:e]]
        else:
            out = text.splitlines()
    print("\n".join("   " + l for l in out).rstrip())
    print()


def utf8_out():
    """Write UTF-8 whatever the console's code page is.

    Windows consoles default to cp1252, which cannot encode an arrow, a curly
    quote or a pound sign, and notes are full of them.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def main():
    utf8_out()
    if len(sys.argv) < 2:
        sys.exit('usage: python search.py "your question"')
    query = " ".join(sys.argv[1:])
    if not DB.is_file():
        sys.exit("no index yet: run python build_index.py first")
    db = sqlite3.connect(DB)

    legs = {"keyword": keyword_leg(db, query)}
    meaning = meaning_leg(db, query)
    if meaning is None:
        print("meaning leg off (pip install fastembed), keyword only\n")
    else:
        legs["meaning"] = meaning

    ranked, found_by = fuse(legs)
    if not ranked:
        print("no matches")
        return
    for position, rowid in enumerate(ranked[:TOP], start=1):
        show(db, rowid, position, found_by[rowid])


if __name__ == "__main__":
    main()
