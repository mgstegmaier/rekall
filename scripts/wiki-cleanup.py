#!/usr/bin/env python3
"""Wiki retire-and-cleanup job.

Deletes wiki pages Mike marked `status: retired` in frontmatter, and cleans up
references. Can also clean up after pages already deleted by hand (--gone).

The mark is the permission: this script only ever deletes marked pages (or
processes names Mike explicitly passes). Everything else in the vault stays
under the never-delete rule.

Per page removed:
  - unlink wikilinks vault-wide: [[name|alias]] -> alias, [[name]] -> name
  - meeting-note targets: annotate citations '(source: name.md)' -> '... — retired)'
  - remove its wiki/index.md entry
  - delete the file (skipped for --gone, already deleted)
  - append one audit entry to wiki/log.md

Usage:
  python3 wiki-cleanup.py                 # dry-run: report what would happen
  python3 wiki-cleanup.py --execute       # do it
  python3 wiki-cleanup.py --gone bigeye --execute   # clean up after a hand-delete
"""

import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rekall_config import VAULT, WIKI  # noqa: E402
_ARGS = sys.argv[1:]
EXECUTE = "--execute" in _ARGS
GONE = []
if "--gone" in _ARGS:
    _i = _ARGS.index("--gone") + 1
    while _i < len(_ARGS) and not _ARGS[_i].startswith("--"):
        GONE.append(_ARGS[_i])
        _i += 1
    if not GONE:
        sys.exit("--gone requires at least one page name after it")
_STRAY = [a for a in _ARGS if not a.startswith("--") and a not in GONE]
if _STRAY:
    sys.exit(f"unexpected argument(s): {_STRAY} — page names must follow --gone")
MEETING_NAME = re.compile(r"^\d{4}-\d{2}-\d{2}-")


def find_marked():
    marked = []
    for p in WIKI.rglob("*.md"):
        if "daily-notes-archive" in p.parts or p.name in ("index.md", "log.md", "CLAUDE.md"):
            continue
        text = p.read_text()
        if text.startswith("---\n"):
            end = text.find("\n---\n", 4)
            if end != -1 and re.search(r"^status:\s*retired\s*$", text[4:end], re.M):
                marked.append(p)
    return marked


def unlink_refs(name):
    """Rewrite references to `name` across the vault. Returns list of touched files."""
    link = re.compile(r"\[\[" + re.escape(name) + r"(#[^\]|]*)?(\|([^\]]*))?\]\]")
    cite = re.compile(r"\(source:\s*" + re.escape(name) + r"(\.md)?\)")
    touched = []
    for p in VAULT.rglob("*.md"):
        if ".obsidian" in p.parts or ".haunt" in p.parts:
            continue
        text = p.read_text()
        new = link.sub(lambda m: m.group(3) if m.group(3) else name, text)
        if MEETING_NAME.match(name):
            new = cite.sub(f"(source: {name}.md — retired)", new)
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


def validate_gone(name):
    """A --gone name must have left traces (a wikilink somewhere in the vault) — refuse typos."""
    pat = re.compile(r"\[\[" + re.escape(name) + r"[#|\]]")
    for p in VAULT.rglob("*.md"):
        if ".obsidian" in p.parts or ".haunt" in p.parts:
            continue
        if pat.search(p.read_text()):
            return True
    return False


def main():
    for name in GONE:
        live = [p for p in WIKI.rglob(f"{name}.md") if "daily-notes-archive" not in p.parts]
        if live:
            sys.exit(f"--gone {name}: page still exists ({live[0].relative_to(VAULT)}) — "
                     "mark it `status: retired` instead; --gone is only for pages already deleted by hand")
        if not validate_gone(name):
            sys.exit(f"--gone {name}: no references found anywhere in the vault — refusing (typo?)")
    marked = find_marked()
    targets = [(p.stem, p) for p in marked] + [(n, None) for n in GONE]
    if not targets:
        print("nothing to do: no pages marked `status: retired`, no --gone names given")
        return
    print(f"{'EXECUTING' if EXECUTE else 'DRY-RUN'}: {len(targets)} target(s)\n")

    audit = []
    for name, path in targets:
        touched = unlink_refs(name)
        had_index = drop_index_entry(name)
        print(f"{name}:")
        print(f"  file: {'delete ' + str(path.relative_to(VAULT)) if path else 'already gone (--gone)'}")
        print(f"  references unlinked in {len(touched)} file(s): {touched}")
        print(f"  index entry: {'removed' if had_index else 'none'}")
        if path and EXECUTE:
            path.unlink()
        audit.append(f"- [[deleted]] `{name}` — references unlinked in {len(touched)} file(s)"
                     + (f": {', '.join(touched)}" if touched else ""))

    if EXECUTE:
        log = WIKI / "log.md"
        log.write_text(log.read_text().rstrip("\n") + f"""

## {date.today()}

**cleanup | retired pages removed**

{chr(10).join(audit)}

Pages were marked `status: retired` by Mike (or named via --gone after a hand-delete); this job unlinked references, removed index entries, and deleted the files. Meeting-note citations, if any, were annotated '— retired' rather than removed.
""")
        print("\nlog.md audit entry appended")
    else:
        print("\n(dry-run — rerun with --execute)")


if __name__ == "__main__":
    main()
