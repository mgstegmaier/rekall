#!/usr/bin/env python3
"""Wiki lifecycle job: archive files marked `status: archive`.

Every page carries `status` (wiki/CLAUDE.md "Page lifecycle"):
  active   normal
  retired  stays put, still linkable and searchable; the pipeline stops updating it
  archive  the mark for this job: move the file to wiki/archive/ ([wiki].archive in rekall.toml)

Archiving MOVES, never deletes. Obsidian resolves [[wikilinks]] by basename across the
vault, so links keep working, and the index, lint, recall index and graph all skip
archive/. Nothing is rewritten. The mark is the permission: only marked files move.

Applies to pages/, meetings/ and raw/*.md (a raw file needs a frontmatter block to
carry the mark). Reports would-be orphans -- pages whose every inbound wikilink came
from the files being archived -- as candidates for you to mark. Never cascades.

--stamp       write `status: active` into every pages/ and meetings/ file lacking status
--gone NAME   a page you already deleted by hand: unlink [[NAME]] vault-wide and drop its
              index entry (the one case that still rewrites other files)

Usage:
  python3 wiki-cleanup.py                       # dry-run: report what would happen
  python3 wiki-cleanup.py --execute
  python3 wiki-cleanup.py --stamp --execute
  python3 wiki-cleanup.py --gone old-page --execute
"""

import argparse
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rekall_config import ARCHIVE, VAULT, WIKI  # noqa: E402

STAMPED_DIRS = ("pages", "meetings")
MARKABLE_DIRS = STAMPED_DIRS + ("raw",)
STATUSES = ("active", "retired", "archive")
MEETING_NAME = re.compile(r"^\d{4}-\d{2}-\d{2}-")
LINK = re.compile(r"\[\[([^\]|#]+)")

ap = argparse.ArgumentParser()
ap.add_argument("--execute", action="store_true")
ap.add_argument("--stamp", action="store_true")
ap.add_argument("--gone", nargs="+", default=[], metavar="NAME")
ARGS = ap.parse_args()
EXECUTE = ARGS.execute


def frontmatter(text):
    """The YAML block between the leading --- fences, or None."""
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---\n", 4)
    return text[4:end] if end != -1 else None


def status_of(text):
    fm = frontmatter(text)
    m = re.search(r"^status:\s*(\S+)\s*$", fm, re.M) if fm else None
    return m.group(1) if m else None


def vault_md():
    for p in VAULT.rglob("*.md"):
        if not any(part.startswith(".") for part in p.relative_to(VAULT).parts):
            yield p


def find_marked():
    return sorted(p for d in MARKABLE_DIRS for p in (WIKI / d).glob("*.md")
                  if status_of(p.read_text(encoding="utf-8", errors="replace")) == "archive")


def would_orphan(archived):
    """pages/ files whose every inbound wikilink comes from the files being archived."""
    gone = {p.stem for p in archived}
    inbound = {}
    for p in (WIKI / "pages").glob("*.md"):
        inbound.setdefault(p.stem, set())
    for p in vault_md():
        if ARCHIVE.name in p.parts or p.name in ("index.md", "log.md", "CLAUDE.md"):
            continue
        for target in LINK.findall(p.read_text(encoding="utf-8", errors="replace")):
            target = target.strip().rsplit("/", 1)[-1]
            if target in inbound and target != p.stem:
                inbound[target].add(p.stem)
    return sorted(s for s, src in inbound.items() if src and src <= gone and s not in gone)


def unlink_refs(name):
    """--gone only: rewrite references to `name` across the vault. Returns touched files."""
    link = re.compile(r"\[\[" + re.escape(name) + r"(#[^\]|]*)?(\|([^\]]*))?\]\]")
    cite = re.compile(r"\(source:\s*" + re.escape(name) + r"(\.md)?\)")
    touched = []
    for p in vault_md():
        text = p.read_text(encoding="utf-8", errors="replace")
        new = link.sub(lambda m: m.group(3) if m.group(3) else name, text)
        if MEETING_NAME.match(name):
            new = cite.sub(f"(source: {name}.md — gone)", new)
        if new != text:
            touched.append(str(p.relative_to(VAULT)))
            if EXECUTE:
                p.write_text(new)
    return touched


def drop_index_entry(name):
    idx = WIKI / "index.md"
    lines = idx.read_text().split("\n")
    kept = [l for l in lines if not l.startswith(f"- [[{name}]]")]
    if len(kept) != len(lines) and EXECUTE:
        idx.write_text("\n".join(kept))
    return len(kept) != len(lines)


def append_log(title, body):
    log = WIKI / "log.md"
    log.write_text(log.read_text().rstrip("\n") + f"\n\n## {date.today()}\n\n**cleanup | {title}**\n\n{body}\n")
    print("\nlog.md audit entry appended")


def stamp():
    todo, skipped = [], []
    for d in STAMPED_DIRS:
        for p in sorted((WIKI / d).glob("*.md")):
            text = p.read_text(encoding="utf-8", errors="replace")
            fm = frontmatter(text)
            if fm is None:
                skipped.append(p)
            elif status_of(text) is None:
                todo.append((p, text, fm))
    for p, text, fm in todo:
        # after the type: line when there is one, else first line of the block
        new_fm = re.sub(r"(?m)^(type:.*)$", r"\1\nstatus: active", fm, count=1) \
            if re.search(r"(?m)^type:", fm) else f"status: active\n{fm}"
        if EXECUTE:
            p.write_text(text.replace(fm, new_fm, 1))
    print(f"{'stamped' if EXECUTE else 'would stamp'} status: active on {len(todo)} file(s)")
    for p in skipped:
        print(f"  no frontmatter, skipped: {p.relative_to(WIKI)}")
    if todo and EXECUTE:
        append_log("status stamped", f"`status: active` written into {len(todo)} pages/ and meetings/ files "
                   "that carried no status (three-stage lifecycle introduced 2026-09-04).")


def gone(names):
    for name in names:
        live = [p for p in WIKI.rglob(f"{name}.md") if "daily-notes-archive" not in p.parts]
        if live:
            sys.exit(f"--gone {name}: page still exists ({live[0].relative_to(VAULT)}); "
                     "mark it `status: archive` instead. --gone is only for pages already deleted by hand")
        if not any(re.search(r"\[\[" + re.escape(name) + r"[#|\]]", p.read_text(encoding="utf-8", errors="replace"))
                   for p in vault_md()):
            sys.exit(f"--gone {name}: no references found anywhere in the vault; refusing (typo?)")
    audit = []
    for name in names:
        touched = unlink_refs(name)
        had_index = drop_index_entry(name)
        print(f"{name}: references unlinked in {len(touched)} file(s): {touched}; "
              f"index entry {'removed' if had_index else 'none'}")
        audit.append(f"- `{name}` (deleted by hand) — references unlinked in {len(touched)} file(s)"
                     + (f": {', '.join(touched)}" if touched else ""))
    if EXECUTE:
        append_log("hand-deleted pages unlinked", "\n".join(audit))


def archive():
    marked = find_marked()
    if not marked:
        print("nothing to do: no files marked `status: archive`")
        return
    print(f"{'EXECUTING' if EXECUTE else 'DRY-RUN'}: {len(marked)} file(s) marked archive\n")
    orphans = would_orphan(marked)
    audit = []
    for p in marked:
        dest = ARCHIVE / p.name
        if dest.exists():
            print(f"  SKIP {p.relative_to(WIKI)}: {dest.relative_to(WIKI)} already exists")
            continue
        had_index = drop_index_entry(p.stem)
        print(f"  {p.relative_to(WIKI)} -> {dest.relative_to(WIKI)}"
              + ("  (index entry removed)" if had_index else ""))
        if EXECUTE:
            ARCHIVE.mkdir(exist_ok=True)
            p.rename(dest)
        audit.append(f"- [[{p.stem}]] moved from `{p.parent.name}/` to `archive/`")
    if orphans:
        print(f"\n  would-be orphans (every inbound link came from the archived files; "
              f"mark `status: archive` yourself if they should go too):")
        for s in orphans:
            print(f"    [[{s}]]")
    if EXECUTE and audit:
        append_log("files archived", "\n".join(audit) + "\n\nMarked `status: archive` by the owner; "
                   "moved, not deleted. Wikilinks resolve by basename so nothing was rewritten."
                   + (f"\n\nWould-be orphans, not touched: {', '.join(f'[[{s}]]' for s in orphans)}" if orphans else ""))
    elif not EXECUTE:
        print("\n(dry-run — rerun with --execute)")


if __name__ == "__main__":
    if ARGS.stamp:
        stamp()
    elif ARGS.gone:
        gone(ARGS.gone)
    else:
        archive()
