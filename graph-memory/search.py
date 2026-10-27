"""Search the index: keyword leg + meaning leg, merged with rank fusion.

Usage: python search.py "your question"
Prints the top hits with the lines around them, and which leg found each.
"""

import functools
import re
import sqlite3
import sys
from datetime import date
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from paths import DB, EMBEDDING_MODEL, MODEL_DIR  # noqa: E402
K = 60  # rank fusion smoothing constant
# recency: a chunk's fused score is scaled by FLOOR + (1-FLOOR) * 0.5**(age/HALF_LIFE),
# so today's chunk keeps 100%, a 90-day-old one 95%, and nothing drops below 90%.
# The floor is high because RRF scores are compressed (rank 0 = 1/60, rank 9 =
# 1/69): 0.9 costs an old chunk at most ~7 ranks in one leg, so recency breaks
# near-ties instead of becoming the sort. A 0.5 floor changed top-4 membership
# on 153 of 231 frozen eval prompts with hits; 0.9 changed it on 57 (2026-10-18).
# Undated chunks are left alone. Dates come from build_index.chunk_date.
HALF_LIFE_DAYS = 90
RECENCY_FLOOR = 0.9
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


# ponytail: a "strong" keyword hit is one of the keyword leg's top STRONG_TOP chunks that holds
# every rare name-like token of the prompt: written with a capital or a digit (Tobias, SNOW-1234;
# the first word needs all-caps or a digit, since grammar capitalises it),
# in at most RARE_DF chunks. Measured 2026-10-27 on the live index (14,279 chunks): names
# sit at 22-24 chunks, while lowercase coding words that are just as rare (recursion, dataclass)
# would let generic prompts through, hence the capital-or-digit test. A token in no chunk at all
# still counts as rare, so a prompt naming something the notes lack ("Xyzzy Nonsense") gets
# nothing. Ceilings: RARE_DF is absolute, so scale it if the index grows several-fold; a name
# typed in lowercase gets no keyword pass (the meaning leg still applies).
STRONG_TOP = 3
RARE_DF = 30


def strong_keyword_hits(db, query, keyword_ids):
    """The keyword-leg rowids that hold every rare name-like query token; empty when there is none."""
    # the first word is capitalised by grammar ("Please ...", "Debug this"), so there only
    # all-caps or a digit marks a name; a one-word name prompt ("Tobias") gets no keyword pass
    rare = [t.lower() for t in dict.fromkeys(
        t for i, t in enumerate(re.findall(r"\w+", query))
        if ((t.isupper() or any(c.isdigit() for c in t)) if i == 0 else not t.islower()))
        if t.lower() not in STOPWORDS]
    # ponytail: one count query per token; the first 20 bound the cost of a pasted log
    rare = [t for t in rare[:20] if db.execute(
        "SELECT count(*) FROM chunks_fts WHERE chunks_fts MATCH ?", (f'"{t}"',)).fetchone()[0] <= RARE_DF]
    if not rare or not keyword_ids:
        return set()
    match = " AND ".join(f'"{t}"' for t in rare)
    holding = {r[0] for r in db.execute("SELECT rowid FROM chunks_fts WHERE chunks_fts MATCH ?", (match,))}
    return {rowid for rowid in keyword_ids[:STRONG_TOP] if rowid in holding}


@functools.lru_cache(maxsize=1)  # the MCP server is long-lived; the hook is one process per prompt
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


def meaning_leg(db, query, scores=None):
    """Top rowids by cosine similarity. When `scores` is a dict, it's filled
    with {rowid: cosine} for the returned ids so a caller can threshold on
    the raw similarity instead of just the rank (recall_hook does)."""
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
    sims = matrix @ q
    top = np.argsort(-sims)[:10]
    if scores is not None:
        scores.update({ids[i]: float(sims[i]) for i in top})
    return [ids[i] for i in top]


def recency(chunk_date, today):
    """The multiplier for a chunk dated chunk_date (YYYY-MM-DD) as of today."""
    age = max(0, (today - date.fromisoformat(chunk_date)).days)
    return RECENCY_FLOOR + (1 - RECENCY_FLOOR) * 0.5 ** (age / HALF_LIFE_DAYS)


def chunk_dates(db, rowids):
    """{rowid: date} for the dated ones; {} on an index built before chunks.date."""
    if not rowids:
        return {}
    marks = ",".join("?" * len(rowids))
    try:
        rows = db.execute(f"SELECT id, date FROM chunks WHERE id IN ({marks}) AND date IS NOT NULL",
                          list(rowids)).fetchall()
    except sqlite3.OperationalError:  # pre-upgrade index: no date column until the next build
        return {}
    return dict(rows)


def fuse(legs, db=None, today=None):
    """Rank fusion over the legs; with db, each score is scaled by recency."""
    scores, found_by = {}, {}
    for name, ids in legs.items():
        for rank, rowid in enumerate(ids):
            scores[rowid] = scores.get(rowid, 0.0) + 1.0 / (K + rank)
            found_by.setdefault(rowid, []).append(name)
    if db is not None:
        today = today or date.today()
        for rowid, d in chunk_dates(db, scores).items():
            try:
                scores[rowid] *= recency(d, today)
            except ValueError:  # malformed date: leave the score alone
                pass
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

    ranked, found_by = fuse(legs, db)
    if not ranked:
        print("no matches")
        return
    for position, rowid in enumerate(ranked[:TOP], start=1):
        show(db, rowid, position, found_by[rowid])


if __name__ == "__main__":
    main()
