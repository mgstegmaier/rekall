"""Write a context sentence for every chunk, through claude -p.

    python contextualize.py --dry-run
    python contextualize.py --limit 10

Anthropic's contextual retrieval (docs/plans/2026-09-13-contextual-retrieval.md,
option 3): a chunk indexed on its own loses the page it came from, so a model
writes one or two sentences that put it back. One call per page, not per chunk:
the whole page goes in once with the list of its sections that still need a
context, and the reply is a JSON object keyed by section heading.

Contexts live in their own `contexts` table in rag.db, keyed by the sha256 of the
chunk body. build_index.py's schema does not know about it, so a --full rebuild
leaves it alone: an unchanged chunk keeps its context forever, a changed one is
written again. Nothing here raises past main(); a page that fails keeps the
deterministic title-and-description prefix build_index already puts in front.
"""

import argparse
import hashlib
import json
import re
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from build_index import chunk_file, note_files, utf8_out  # noqa: E402
from distil import CONFIG, ask  # noqa: E402
from paths import DB, WIKI  # noqa: E402

PROMPT = HERE / "contextualize-prompt.md"
BATCH = 40  # sections per call; pages here are far smaller, this is the guard
TABLE = """CREATE TABLE IF NOT EXISTS contexts (
    file TEXT NOT NULL,
    section TEXT NOT NULL,
    text_hash TEXT NOT NULL,
    context TEXT NOT NULL,
    model TEXT NOT NULL,
    at TEXT NOT NULL,
    PRIMARY KEY (file, section, text_hash)
)"""
FM_LINE = re.compile(r"^(title|type|description|owner):\s*(.+)$")
WIKILINK = re.compile(r"\[\[([^\]|#]+)")


def model_name():
    """contextualize_model from digest/config.json, or haiku. Short calls, cheap model."""
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8")).get("contextualize_model") or "haiku"
    except Exception:
        return "haiku"


def page_meta(lines):
    """title/type/description/owner from the leading YAML block.

    build_index's frontmatter() keeps only the two keys it indexes; the
    contextualizer is handed the other two as well.
    """
    if not lines or lines[0].strip() != "---":
        return {}
    meta = {}
    for line in lines[1:]:
        if line.strip() == "---":
            return meta
        m = FM_LINE.match(line)
        if m:
            meta[m.group(1)] = m.group(2).strip().strip('"')
    return {}  # unterminated block: not frontmatter


def text_hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def pending(db, rel, chunks):
    """The (section, hash, text) chunks of one file that have no context yet."""
    have = {(r[0], r[1]) for r in
            db.execute("SELECT section, text_hash FROM contexts WHERE file = ?", (rel,))}
    out = []
    for section, _start, _end, text in chunks:
        digest = text_hash(text)
        if (section, digest) not in have:
            out.append((section, digest, text))
    return out


def parse_reply(text):
    """The JSON object in a reply, fences and chatter allowed around it."""
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("no JSON object in the reply")
    got = json.loads(m.group(0))
    if not isinstance(got, dict):
        raise ValueError("the reply is not an object")
    return got


def payload(rel, meta, body, batch):
    """The page and the sections that need a context, for one call."""
    head = [f"page: {rel}"]
    head += [f"{k}: {meta[k]}" for k in ("title", "type", "description", "owner") if meta.get(k)]
    lines = [*head, "", "<document>", body, "</document>", "", "sections needing context:"]
    for section, links in batch:
        named = ", ".join(dict.fromkeys(l.strip() for l in links if l.strip()))
        lines.append(f'- "{section}"' + (f" — links: {named}" if named else ""))
    return "\n".join(lines)


def contextualize_file(rel, path, need, model, prompt_text):
    """{section: context} for one page's pending sections. Raises if a call fails."""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    meta = page_meta(lines)
    sections = {}  # section -> links, in the order the chunks come
    for section, _digest, text in need:
        sections.setdefault(section, []).extend(WIKILINK.findall(text))
    body = "\n".join(lines)
    items = list(sections.items())
    out = {}
    for i in range(0, len(items), BATCH):
        out.update(parse_reply(ask(model, prompt_text, payload(rel, meta, body, items[i:i + BATCH]))))
    return out


def run(corpus, limit=None, dry_run=False, workers=4):
    """Contextualize the chunks under corpus that have none. Returns the counts."""
    corpus = Path(corpus).resolve()
    if not corpus.is_dir():
        raise RuntimeError(f"not a folder: {corpus}")
    started = time.time()
    db = sqlite3.connect(DB)
    # the nightly rebuild can be holding the write lock for minutes; wait it out
    db.execute("PRAGMA busy_timeout=60000")
    if db.execute("PRAGMA journal_mode").fetchone()[0] != "wal":
        db.execute("PRAGMA journal_mode=WAL")
    db.execute(TABLE)

    todo = []
    for path in note_files(corpus):
        rel = path.relative_to(corpus).as_posix()
        try:
            _meta, chunks = chunk_file(path)
        except Exception as exc:
            print(f"contextualize: skipped {rel}: {type(exc).__name__} {exc}", file=sys.stderr)
            continue
        need = pending(db, rel, chunks)
        if need:
            todo.append((rel, path, need))

    counts = {"files": len(todo), "chunks": sum(len(n) for _r, _p, n in todo), "skipped": 0}
    if dry_run:
        print(f"contextualize: {counts['files']} files, {counts['chunks']} chunks need context")
        return counts

    model = model_name()
    prompt_text = PROMPT.read_text(encoding="utf-8")
    if limit is not None:
        todo = todo[:limit]
    counts.update(files=len(todo), chunks=0, skipped=0)
    # the calls wait on a subprocess, so threads are enough. Every sqlite write
    # stays here on the main thread: one writer, one connection, no locking.
    pool = ThreadPoolExecutor(max_workers=max(1, workers))
    futures = {pool.submit(contextualize_file, rel, path, need, model, prompt_text):
               (rel, need) for rel, path, need in todo}
    for future in as_completed(futures):
        rel, need = futures[future]
        try:
            contexts = future.result()
        except Exception as exc:  # one bad page never stops the run
            print(f"contextualize: skipped {rel}: {type(exc).__name__} {exc}", file=sys.stderr)
            counts["skipped"] += len(need)
            continue
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        rows = [(rel, section, digest, contexts[section].strip(), model, now)
                for section, digest, _text in need
                if isinstance(contexts.get(section), str) and contexts[section].strip()]
        if len(rows) < len(need):
            print(f"contextualize: {rel}: {len(need) - len(rows)} sections missing from the reply",
                  file=sys.stderr)
        db.executemany("INSERT OR REPLACE INTO contexts VALUES (?, ?, ?, ?, ?, ?)", rows)
        db.commit()
        counts["chunks"] += len(rows)
        counts["skipped"] += len(need) - len(rows)
    pool.shutdown()
    db.close()

    print(f"contextualize: {counts['files']} files, {counts['chunks']} chunks contextualized, "
          f"{counts['skipped']} skipped, {time.time() - started:.1f}s")
    return counts


def main():
    utf8_out()
    ap = argparse.ArgumentParser(description="Write a context sentence per chunk.")
    ap.add_argument("--corpus", default=str(WIKI), help="the folder build_index indexes")
    ap.add_argument("--limit", type=int, default=None, help="process at most N files")
    ap.add_argument("--dry-run", action="store_true", help="count what needs context and stop")
    ap.add_argument("--workers", type=int, default=4, help="pages in flight at once")
    args = ap.parse_args()
    try:
        run(args.corpus, limit=args.limit, dry_run=args.dry_run, workers=args.workers)
    except Exception as exc:
        sys.exit(f"contextualize: {exc}")


if __name__ == "__main__":
    main()
