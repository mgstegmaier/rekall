"""Build the index: chunk markdown on headings, index keywords and meaning.

Reads ../corpus-before by default, plus any distilled entries in
~/obsidian-vault/graph-memory/distilled/ (kept out of the repo: meeting content).
Subfolders are included, so the digest's daily/ folder is indexed like any note.
Writes rag.db next to this script. Run again any time; the index is disposable.

Runs are incremental by default: a content hash per file (files table) means
only new, changed, and deleted files are re-chunked and re-embedded. --full
drops everything and rebuilds — the weekly self-heal, and required after an
embedding-model change (stored vectors from the old model are invalid).
"""

import argparse
import hashlib
import os
import re
import sqlite3
import struct
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from paths import DB, DISTILLED_DIR  # noqa: E402
CHUNK_BUDGET = 1600  # characters, roughly 400 tokens
SKIP_DIRS = {".git", "node_modules", "__pycache__"}

SCHEMA = """
DROP TABLE IF EXISTS chunks;
DROP TABLE IF EXISTS chunks_fts;
DROP TABLE IF EXISTS vectors;
DROP TABLE IF EXISTS meta;
DROP TABLE IF EXISTS files;
CREATE TABLE files (path TEXT PRIMARY KEY, hash TEXT NOT NULL, src TEXT);
CREATE TABLE chunks (
    id INTEGER PRIMARY KEY,
    file TEXT NOT NULL,
    section TEXT NOT NULL,
    start_line INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    text TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'chunk'
);
CREATE VIRTUAL TABLE chunks_fts USING fts5(text, file, section);
CREATE TABLE vectors (id INTEGER PRIMARY KEY, vec BLOB NOT NULL);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def note_files(corpus):
    """Every markdown file under the corpus, subfolders included.

    Skipped: hidden files and folders, .git, node_modules, __pycache__, and
    this starter's own folder when it has been cloned inside the notes.
    """
    root = Path(corpus).resolve()
    starter = HERE.parent.resolve()
    # the starter is skipped only when it sits INSIDE your notes, which is the
    # case the rule exists for. A corpus inside the starter is the bundled demo
    # folders, and those are meant to be indexed.
    skip_starter = starter != root and root in starter.parents
    out = []
    for path in sorted(root.rglob("*.md")):
        rel = path.relative_to(root)
        if any(part.startswith(".") or part in SKIP_DIRS for part in rel.parts):
            continue
        if skip_starter and (starter == path.parent or starter in path.parents):
            continue
        out.append(path)
    return out


def sections(lines):
    """Split markdown lines into (heading, start, end) sections."""
    out = []
    heading, start = None, 0
    for i, line in enumerate(lines):
        if re.match(r"^#{1,3} ", line):
            if i > start or heading is not None:
                out.append((heading, start, i))
            heading, start = line.lstrip("# ").strip(), i
    out.append((heading, start, len(lines)))
    return [(h, s, e) for h, s, e in out if any(l.strip() for l in lines[s:e])]


FM_KEYS = ("title", "description")


def frontmatter(lines):
    """Parse a leading YAML block for single-line keys. Returns (meta, body_start).

    Only the keys in FM_KEYS are kept; the block itself is skipped by the
    chunker so tags and source lists never pollute the index.
    """
    if not lines or lines[0].strip() != "---":
        return {}, 0
    meta = {}
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return meta, i + 1
        m = re.match(r"([\w-]+):\s*(.+)", line)
        if m and m.group(1) in FM_KEYS:
            meta[m.group(1)] = m.group(2).strip().strip('"')
    return {}, 0  # unterminated block: treat it as body


def chunk_file(path):
    """Return (frontmatter meta, [(section, start_line, end_line, text)] chunks)."""
    lines = path.read_text(encoding="utf-8").splitlines()
    meta, off = frontmatter(lines)
    packed = []
    for heading, s, e in ((h, s + off, e + off) for h, s, e in sections(lines[off:])):
        text = "\n".join(lines[s:e]).strip()
        title = heading or path.stem
        if len(text) <= CHUNK_BUDGET:
            packed.append((title, s + 1, e, text))
            continue
        # oversized section: split on line groups within the budget
        buf, buf_start = [], s
        for i in range(s, e):
            buf.append(lines[i])
            if sum(len(l) + 1 for l in buf) >= CHUNK_BUDGET:
                packed.append((title, buf_start + 1, i + 1, "\n".join(buf).strip()))
                buf, buf_start = [], i + 1
        if any(l.strip() for l in buf):
            packed.append((title, buf_start + 1, e, "\n".join(buf).strip()))
    return meta, packed


def parse_entry(text):
    """Read a distilled entry: source, questions, summary, rule, quote.

    distil.py checks its own output through this, so the writer and the reader
    can never drift into two spellings of the format.
    """
    entry = {"questions": []}
    for line in text.splitlines():
        if line.startswith("source:"):
            entry["source"] = line.split(":", 1)[1].strip()
        elif line.startswith("- "):
            entry["questions"].append(line[2:].strip())
        elif line.startswith("summary:"):
            entry["summary"] = line.split(":", 1)[1].strip()
        elif line.startswith("rule:"):
            entry["rule"] = line.split(":", 1)[1].strip()
        elif line.startswith("quote:"):
            entry["quote"] = line.split(":", 1)[1].strip().strip('"')
    return entry


def parse_distilled(path):
    """Read a distilled entry from a file."""
    return parse_entry(path.read_text(encoding="utf-8"))


def normalise(text):
    return " ".join(text.split())


def utf8_out():
    """Write UTF-8 whatever the console's code page is.

    Windows consoles default to cp1252, which cannot encode an arrow, a curly
    quote or a pound sign, and file names and notes are full of them.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def file_docs(rel, path):
    """(embed_text, row) docs for one corpus file."""
    meta, chunks = chunk_file(path)
    docs = []
    if meta.get("description"):
        # one page-level row from the curated frontmatter hook
        text = f"{meta.get('title') or path.stem}: {meta['description']}"
        docs.append((f"[{rel} § description]\n" + text,
                     (rel, "description", 0, 0, text, "description")))
    for section, s, e, text in chunks:
        docs.append((f"[{rel} § {section}]\n" + text,
                     (rel, section, s, e, text, "chunk")))
    return docs


def distilled_doc(path, corpus):
    """(embed_text, row, source_rel) for one distilled file, or None if the
    quote fails grounding: the quote must appear in the source, word for word."""
    entry = parse_distilled(path)
    source = corpus / entry.get("source", "")
    quote = entry.get("quote", "")
    if not source.is_file() or normalise(quote) not in normalise(source.read_text(encoding="utf-8")):
        return None
    body = "\n".join(
        entry["questions"]
        + [entry.get("summary", ""), entry.get("rule", ""), quote]
    ).strip()
    label = f"[{entry['source']} § distilled]"
    row = (entry["source"], "distilled", 0, 0, body, "distilled")
    return label + "\n" + body, row, entry["source"]


def purge(db, key, src):
    """Remove one tracked file's rows from chunks, fts, vectors, and files."""
    if key.startswith("distilled/"):
        where, params = "file = ? AND kind = 'distilled'", (src,)
    else:
        where, params = "file = ? AND kind != 'distilled'", (key,)
    ids = [(r[0],) for r in db.execute(f"SELECT id FROM chunks WHERE {where}", params)]
    db.executemany("DELETE FROM chunks WHERE id = ?", ids)
    db.executemany("DELETE FROM chunks_fts WHERE rowid = ?", ids)
    db.executemany("DELETE FROM vectors WHERE id = ?", ids)
    db.execute("DELETE FROM files WHERE path = ?", (key,))


def main():
    utf8_out()
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default=str(HERE.parent / "corpus-before"))
    ap.add_argument("--extra", action="append", default=[],
                    help="extra folder to index (e.g. the vault's memory/sessions)")
    ap.add_argument("--full", action="store_true",
                    help="drop and rebuild everything; required after an embedding-model change")
    args = ap.parse_args()
    corpus = Path(args.corpus)

    db = sqlite3.connect(DB)
    # incremental needs a DB built with the files table and a matching corpus;
    # anything else (first run, pre-upgrade DB, corpus moved) forces a full build
    full = args.full
    if not full:
        has_files = db.execute("SELECT name FROM sqlite_master WHERE name='files'").fetchone()
        stored = db.execute("SELECT value FROM meta WHERE key='corpus'").fetchone() if has_files else None
        full = not has_files or not stored or stored[0] != str(corpus.resolve())
    if not full:
        # weekly nuke-and-pave: the first run on a Sunday promotes itself to full.
        # This lives here rather than in cron so a Mac asleep at the scheduled hour
        # still gets its weekly full on the first Sunday run after it wakes.
        today = date.today()
        last_full = db.execute("SELECT value FROM meta WHERE key='last_full'").fetchone()
        full = today.isoweekday() == 7 and (not last_full or last_full[0] != today.isoformat())
    if full:
        db.executescript(SCHEMA)
        db.execute("INSERT INTO meta VALUES ('corpus', ?)", (str(corpus.resolve()),))
        db.execute("INSERT INTO meta VALUES ('last_full', ?)", (date.today().isoformat(),))

    root = corpus.resolve()
    files = [(p.relative_to(root).as_posix(), p) for p in note_files(corpus)]
    for extra in args.extra:
        extra_root = Path(extra).resolve()
        if not extra_root.is_dir():
            continue
        # rel climbs out of the corpus ("../memory/sessions/x.md") so search.py
        # can still resolve corpus/rel back to the real file for context lines
        files += [(os.path.relpath(p, root).replace(os.sep, "/"), p)
                  for p in note_files(extra_root)]
    distilled_dir = DISTILLED_DIR
    distilled_files = sorted(distilled_dir.glob("*.md")) if distilled_dir.is_dir() else []

    tracked = dict((p, (h, s)) for p, h, s in db.execute("SELECT path, hash, src FROM files"))
    on_disk = [(rel, path, file_hash(path)) for rel, path in files]
    on_disk += [("distilled/" + p.name, p, file_hash(p)) for p in distilled_files]

    # deleted: tracked but no longer on disk
    disk_keys = {key for key, _, _ in on_disk}
    deleted = [k for k in tracked if k not in disk_keys]
    for key in deleted:
        purge(db, key, tracked[key][1])

    # new or changed: (re)chunk, (re)embed
    docs, dropped, changed = [], 0, 0  # docs: (embed_text, row, files_row)
    for key, path, digest in on_disk:
        if key in tracked and tracked[key][0] == digest:
            continue
        changed += 1
        purge(db, key, tracked.get(key, (None, None))[1])
        if key.startswith("distilled/"):
            # ponytail: a source edit can silently unground an already-indexed
            # quote; the weekly --full recheck catches that drift
            got = distilled_doc(path, corpus)
            if got is None:
                dropped += 1
                print(f"dropped {path.name}: quote not found in its source")
                db.execute("INSERT INTO files VALUES (?,?,?)", (key, digest, None))
                continue
            embed_text, row, src = got
            docs.append((embed_text, row, (key, digest, src)))
        else:
            fdocs = file_docs(key, path)
            for embed_text, row in fdocs:
                docs.append((embed_text, row, (key, digest, None)))
            if not fdocs:  # e.g. an empty note still gets tracked so it doesn't rescan
                db.execute("INSERT OR REPLACE INTO files VALUES (?,?,?)", (key, digest, None))

    ids = []
    for embed_text, row, files_row in docs:
        cur = db.execute(
            "INSERT INTO chunks (file, section, start_line, end_line, text, kind) VALUES (?,?,?,?,?,?)",
            row,
        )
        ids.append(cur.lastrowid)
        db.execute(
            "INSERT INTO chunks_fts (rowid, text, file, section) VALUES (?,?,?,?)",
            (cur.lastrowid, embed_text, row[0], row[1]),
        )
        db.execute("INSERT OR REPLACE INTO files VALUES (?,?,?)", files_row)

    model_line = "keyword only (pip install fastembed for the meaning leg)"
    if not on_disk:
        model_line = "nothing to index: no markdown found under the corpus"
    elif not docs:
        model_line = "no new or changed files; index untouched"
    else:
        try:
            from search import embedding_model

            model = embedding_model()
            vecs = list(model.embed([t for t, _, _ in docs]))
            for rowid, vec in zip(ids, vecs):
                norm = sum(x * x for x in vec) ** 0.5 or 1.0
                blob = struct.pack(f"{len(vec)}f", *(x / norm for x in vec))
                db.execute("INSERT INTO vectors (id, vec) VALUES (?,?)", (rowid, blob))
            model_line = f"model {model.model_name} ({len(vecs[0])}d) + keyword sqlite fts5"
        except ImportError:
            pass

    db.commit()
    # invariant: one fts row per chunk, and vectors either cover every chunk or
    # none (keyword-only mode); anything else means a purge/insert bug
    n_chunks = db.execute("SELECT count(*) FROM chunks").fetchone()[0]
    n_fts = db.execute("SELECT count(*) FROM chunks_fts").fetchone()[0]
    n_vec = db.execute("SELECT count(*) FROM vectors").fetchone()[0]
    assert n_fts == n_chunks and n_vec in (0, n_chunks), \
        f"index inconsistent: {n_chunks} chunks, {n_fts} fts, {n_vec} vectors — rerun with --full"
    db.close()
    mode = "full" if full else "incremental"
    print(f"{mode}: {len(files)} files scanned, {changed} new/changed, {len(deleted)} deleted, "
          f"{dropped} dropped; index holds {n_chunks} rows")
    print(model_line)


if __name__ == "__main__":
    main()
