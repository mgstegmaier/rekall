"""Build the wiki graph: one entity per page, one edge per wikilink.

Deterministic — no LLM. Entities come from the wiki's type folders plus
frontmatter title/description; relations are untyped "mentions" edges parsed
from [[wikilinks]] in page bodies. Writes entities/relations/aliases into
rag.db next to this script. Run any time; the tables are disposable.
"""

import argparse
import os
import re
import sqlite3
import uuid
import sys
from pathlib import Path

from build_index import chunk_file, frontmatter, note_files, utf8_out  # noqa: F401

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from paths import DB  # noqa: E402

WIKILINK = re.compile(r"\[\[([^\]|#]+)")

SCHEMA = """
DROP TABLE IF EXISTS entities;
DROP TABLE IF EXISTS relations;
DROP TABLE IF EXISTS aliases;
CREATE TABLE entities  (id TEXT PRIMARY KEY, name TEXT, type TEXT,
                        description TEXT, source_doc TEXT);
CREATE TABLE relations (source_id TEXT, target_id TEXT,
                        predicate TEXT, source_doc TEXT);
CREATE TABLE aliases   (entity_id TEXT, alias TEXT);
"""

TYPE_BY_FOLDER = {
    "people": "person",
    "projects": "project",
    "entities": "entity",
    "concepts": "concept",
    "meetings": "meeting",
    "summaries": "summary",
}


def eid(kind, name):
    return str(uuid.uuid5(uuid.NAMESPACE_OID, f"{kind}:{' '.join(name.lower().split())}"))


def pages(corpus, extras=()):
    """(rel, slug, type, meta, body) per graph-worthy page. Archive folders are skipped."""
    root = Path(corpus).resolve()
    out = []
    for path in note_files(root):
        rel = path.relative_to(root).as_posix()
        kind = TYPE_BY_FOLDER.get(rel.split("/", 1)[0])
        if kind is None:  # index.md, log.md, daily-notes-archive, ...
            continue
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        meta, off = frontmatter(lines)
        out.append((rel, path.stem.lower(), kind, meta, "\n".join(lines[off:])))
    # extra folders (session digests): "session" entities whose wikilinks become
    # edges, so "when did I last touch X" is answerable from the graph. rel climbs
    # out of the corpus ("../memory/sessions/x.md"), matching build_index --extra.
    for extra in extras:
        eroot = Path(extra).resolve()
        if not eroot.is_dir():
            continue
        for path in note_files(eroot):
            rel = os.path.relpath(path, root).replace(os.sep, "/")
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            meta, off = frontmatter(lines)
            meta.setdefault("title", f"session {path.stem}")
            out.append((rel, path.stem.lower(), "session", meta, "\n".join(lines[off:])))
    return out


def main():
    utf8_out()
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", required=True, help="the wiki folder")
    ap.add_argument("--extra", action="append", default=[],
                    help="extra folder of session digests to graph (e.g. the vault's memory/sessions)")
    args = ap.parse_args()

    rows = pages(args.corpus, args.extra)
    by_slug = {}
    ident_by_rel = {}
    db = sqlite3.connect(DB)
    db.executescript(SCHEMA)

    for rel, slug, kind, meta, _ in rows:
        name = meta.get("title") or slug.replace("-", " ")
        ident = eid(kind, name)
        ident_by_rel[rel] = ident
        by_slug.setdefault(slug, ident)  # wiki pages come first; a session never shadows one
        db.execute(
            "INSERT OR IGNORE INTO entities VALUES (?,?,?,?,?)",
            (ident, name, kind, meta.get("description", ""), rel),
        )
        spaced = slug.replace("-", " ")
        if spaced != name.lower():
            db.execute("INSERT INTO aliases VALUES (?,?)", (ident, spaced))

    edges = set()
    for rel, slug, kind, _, body in rows:
        src = ident_by_rel[rel]
        for target in WIKILINK.findall(body):
            t = target.strip().lower()
            # digests may write [[Familiar Cost Watch]]; slugs are hyphenated
            tid = by_slug.get(t) or by_slug.get(t.replace(" ", "-"))
            if tid and tid != src:
                edges.add((src, tid, "mentions", rel))
    db.executemany("INSERT INTO relations VALUES (?,?,?,?)", sorted(edges))

    db.commit()
    db.close()
    print(f"graph: {len(rows)} entities, {len(edges)} edges")


if __name__ == "__main__":
    main()
