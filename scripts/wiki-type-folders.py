#!/usr/bin/env python3
"""Move every wiki page into pages/<type>/, where the folder name is the page's `type` value.

Wikilinks resolve by basename, so a move breaks no links as long as basenames stay unique.
Dry run by default: prints the planned moves and the count per folder. --apply moves the files.
Refuses to move anything if a page has no `type` or two pages share a basename.

    python3 scripts/wiki-type-folders.py            # dry run
    python3 scripts/wiki-type-folders.py --apply
"""
import argparse
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rekall_config import WIKI  # noqa: E402

FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.S)
TYPE_RE = re.compile(r"(?m)^type:\s*['\"]?([a-z0-9-]+)['\"]?\s*$")


def page_type(path):
    m = FRONTMATTER_RE.match(path.read_text(encoding="utf-8", errors="replace"))
    t = TYPE_RE.search(m.group(1)) if m else None
    return t.group(1) if t else None


def plan(pages_dir):
    """(moves, problems). moves is [(src, dest)] for pages outside their type folder."""
    pages = sorted(pages_dir.rglob("*.md"))
    problems = [f"no `type`: {p.relative_to(pages_dir)}" for p in pages if page_type(p) is None]
    names = Counter(p.name for p in pages)
    problems += [f"basename collision: {n} ({c} files)" for n, c in sorted(names.items()) if c > 1]
    moves = [(p, pages_dir / page_type(p) / p.name) for p in pages
             if page_type(p) and p.parent != pages_dir / page_type(p)]
    return moves, problems


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--apply", action="store_true", help="move the files (default: dry run)")
    args = ap.parse_args()

    pages_dir = WIKI / "pages"
    moves, problems = plan(pages_dir)
    if problems:
        print("refusing to move anything:\n  " + "\n  ".join(problems))
        return 1
    for src, dest in moves:
        print(f"{src.relative_to(pages_dir)} -> {dest.relative_to(pages_dir)}")
    per_folder = Counter(dest.parent.name for _, dest in moves)
    print(f"\n{len(moves)} pages to move" + ("" if args.apply else " (dry run; --apply to move)"))
    for folder, n in per_folder.most_common():
        print(f"  pages/{folder}/  {n}")
    if args.apply:
        for src, dest in moves:
            dest.parent.mkdir(exist_ok=True)
            src.rename(dest)
        print(f"moved {len(moves)} pages")
    return 0


if __name__ == "__main__":
    sys.exit(main())
