#!/usr/bin/env python3
"""One-field taxonomy: set `type` from the page's folder and drop `wiki-type`.

Decided 2026-09-04: `type` (the OKF-required field) is the only taxonomy axis, so
other vault note types (note, decision) can join the wiki under the same field later.
Ran 2026-09-04 against the pre-collapse type folders, which were merged into wiki/pages/ the same day;
kept as the record of the migration. Idempotent; backs up every changed file first.

  wiki-retype.py            # apply
  wiki-retype.py --dry-run  # report only
"""
import re
import shutil
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rekall_config import STATE_DIR, WIKI  # noqa: E402

FOLDER_TYPE = {"people": "person", "projects": "project", "entities": "entity",
               "concepts": "concept", "summaries": "summary"}
FM_RE = re.compile(r"\A---\n(.*?)\n---\n", re.S)
BACKUP = STATE_DIR / "backups" / f"retype-{date.today():%Y-%m-%d}"


def retype(path, new_type):
    """Return (new_text, note) or (None, note) when nothing changes."""
    text = path.read_text()
    m = FM_RE.match(text)
    if not m:
        return None, "no frontmatter"
    fm = m.group(1)
    tm = re.search(r"^type:\s*(.*)$", fm, re.M)
    cur = tm.group(1).strip() if tm else None
    if cur not in (None, "wiki-page", new_type):
        return None, f"left alone (type: {cur})"
    fm2 = re.sub(r"^wiki-type:.*\n?", "", fm, flags=re.M)
    if tm:
        fm2 = re.sub(r"^type:.*$", f"type: {new_type}", fm2, count=1, flags=re.M)
    else:
        fm2 = f"type: {new_type}\n{fm2}"
    fm2 = fm2.rstrip("\n")
    if fm2 == fm:
        return None, "already current"
    return f"---\n{fm2}\n---\n{text[m.end():]}", f"type: {cur} -> {new_type}"


def main():
    dry = "--dry-run" in sys.argv
    targets = [(p, t) for folder, t in FOLDER_TYPE.items() for p in sorted((WIKI / folder).glob("*.md"))]
    targets.append((WIKI / "log.md", "log"))
    changed, skipped = 0, []
    for path, new_type in targets:
        new, note = retype(path, new_type)
        if new is None:
            if note not in ("already current",):
                skipped.append(f"{path.relative_to(WIKI)}: {note}")
            continue
        changed += 1
        if not dry:
            BACKUP.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, BACKUP / path.name)
            path.write_text(new)
    print(f"{'would change' if dry else 'changed'} {changed} pages" + (f" (backup: {BACKUP})" if changed and not dry else ""))
    for s in skipped:
        print("  skip", s)
    if changed and not dry:
        log = WIKI / "log.md"
        log.write_text(log.read_text().rstrip("\n") + (
            f"\n\n## {date.today():%Y-%m-%d}\n\n**retype | one-field taxonomy**\n\n"
            f"`type` is now the only taxonomy field (person, project, entity, concept, summary, meeting, log); "
            f"`wiki-type` retired. {changed} pages rewritten by `rekall/scripts/wiki-retype.py` from folder placement; "
            f"originals in `{BACKUP}`. Decision: wiki owner, 2026-09-04, so other vault note types (note, decision) can join "
            f"the wiki under the same field. Pages left alone: {len(skipped)}.\n"))


if __name__ == "__main__":
    main()
