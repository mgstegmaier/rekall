#!/usr/bin/env python3
"""Roll `### Wins` bullets from session digests onto the accomplishments wiki page.

The session-end digest (graph-memory/digest) writes memory/sessions/YYYY-MM-DD.md.
When a work session shipped something with org impact, the digest prompt asks for a
`### Wins` heading. This sweep appends every bullet it has not seen before under the
page's `## Running log (auto)` heading, dated by the session file. Dedupe is by exact
bullet text already present on the page, so it needs no state file and is safe to run
hourly from the Fathom pipeline.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rekall_config import VAULT  # noqa: E402
SESSIONS = VAULT / "memory" / "sessions"
PAGE = VAULT / "wiki" / "entities" / "annual-review-2026-accomplishments.md"
HEADING = "## Running log (auto)"


def main():
    if not PAGE.exists() or not SESSIONS.is_dir():
        return 0
    page = PAGE.read_text(encoding="utf-8")
    new = []
    for f in sorted(SESSIONS.glob("*.md")):
        text = f.read_text(errors="ignore")
        for block in re.findall(r"^### Wins\n(.*?)(?=^### |^## |\Z)", text, re.M | re.DOTALL):
            for line in block.strip().splitlines():
                line = line.strip()
                if line.startswith("-") and line[1:].strip() and line[1:].strip() not in page:
                    new.append(f"- {f.stem} {line[1:].strip()} (source: memory/sessions/{f.name})")
    if not new:
        return 0
    if HEADING not in page:
        page = page.rstrip("\n") + f"\n\n{HEADING}\n"
    page = page.rstrip("\n") + "\n" + "\n".join(new) + "\n"
    PAGE.write_text(page, encoding="utf-8")
    return len(new)


if __name__ == "__main__":
    print(f"wins-sweep: {main()} new")
