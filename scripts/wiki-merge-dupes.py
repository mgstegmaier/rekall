#!/usr/bin/env python3
"""Merge a page's duplicate State / Next steps / Members / Related pages sections into one each.

The judgement half of the page-order rule (wiki/CLAUDE.md, decided 2026-09-04). wiki-reflow.py
puts duplicate sections side by side; this sends ONLY those sections to a headless Claude call
and splices the merged result back, so ## Updates and the reference sections never pass
through the model. Run wiki-reflow.py first: it moves "State (as of DATE)" snapshots into
## Updates, so only true duplicates reach this script.

Accepted only if the reply has exactly one section per group and keeps every citation
(`(source: ...)`) and every [[wikilink]] the inputs had. Otherwise the page is left alone
and the reply is saved next to the report for a look.

Usage:
  wiki-merge-dupes.py PAGE [PAGE ...] [--out DIR]   # dry-run: merged copy into DIR, nothing in the vault
  wiki-merge-dupes.py PAGE ... --write               # rewrite in place; original to STATE_DIR/backups/merge-DATE/
  --model sonnet|opus                                 # default sonnet
"""

import argparse
import importlib.util
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from rekall_config import STATE_DIR, WIKI  # noqa: E402

_spec = importlib.util.spec_from_file_location("reflow", HERE / "wiki-reflow.py")
reflow = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(reflow)

GROUPS = ("State", "Next steps", "Members", "Related pages")
CITE = re.compile(r"\(source: ([^)]+)\)")
LINK = re.compile(r"\[\[([^\]|#]+)")

PROMPT = """You are merging duplicate sections of one wiki project page. The page followed a
"State, Next steps, Members, Updates, reference, Related pages" layout, but earlier merges left
two or more copies of some sections. Below, each group is shown with every copy, oldest copy
first. Produce ONE section per group.

Rules:
- Keep every factual claim and its `(source: ...)` citation. Nothing sourced is dropped; if two
  copies say the same thing, keep it once with both citations.
- Where copies conflict, the newer statement wins and the older one is kept as a one-line
  "Earlier: ..." note with its citation, so the change is visible.
- Next steps: one list. Drop an item only if another copy or the State text says it is done,
  and then keep it struck through (~~like this~~) with the source that closed it.
- Members: one list, deduplicated, roles preserved.
- Related pages: one bulleted list of [[wikilinks]], deduplicated, every link from the inputs
  present, alphabetical.
- Markdown only. Keep sub-headings (###) that the inputs had where they still make sense.
- Output exactly the merged sections, each starting with its `## ` heading, in the order
  State, Next steps, Members, Related pages (only the groups given). No preamble, no
  commentary, no code fence around the whole thing.
"""


def group_of(heading):
    # "State (as of DATE)" snapshots are dated updates; wiki-reflow.py moves them into
    # ## Updates first, so only true duplicate sections reach the merge
    t = reflow.heading_text(heading)
    return t if t in GROUPS else None


def claude_merge(payload, model):
    exe = shutil.which("claude")
    if not exe:
        sys.exit("claude is not on PATH")
    with tempfile.TemporaryDirectory(prefix="wiki-merge-") as scratch:
        proc = subprocess.run([exe, "-p", "--model", model, "--output-format", "text", "--tools", ""],
                              input=PROMPT + "\n\n---\n\n" + payload, capture_output=True, text=True,
                              cwd=scratch, timeout=600)
    if proc.returncode != 0:
        raise RuntimeError(f"claude exit {proc.returncode}: {(proc.stderr or proc.stdout or '').strip()[:300]}")
    return proc.stdout.strip() + "\n"


def merge_page(text, model):
    fm, body = reflow.split_frontmatter(text)
    h2s = reflow.blocks(body.splitlines(), 2)
    members = {g: [] for g in GROUPS}
    for i, (head, blines) in enumerate(h2s[1:], 1):
        g = group_of(head) if head else None
        if g:
            members[g].append(i)
    dupes = {g: idx for g, idx in members.items() if len(idx) > 1}
    if not dupes:
        return None, ["no duplicate sections"], None

    payload_parts, cites, links = [], set(), set()
    for g, idx in dupes.items():
        payload_parts.append(f"# GROUP: {g} ({len(idx)} copies)\n")
        for n, i in enumerate(idx, 1):
            head, blines = h2s[i]
            sec = "\n".join([head] + blines)
            payload_parts.append(f"## copy {n} of {g}\n{sec}\n")
            cites.update(c.strip() for c in CITE.findall(sec))
            links.update(l.strip() for l in LINK.findall(sec))
    reply = claude_merge("\n".join(payload_parts), model)

    merged = {}
    for head, blines in reflow.blocks(reply.splitlines(), 2)[1:]:
        g = group_of(head)
        if g in dupes and g not in merged:
            merged[g] = (f"## {g}", reflow.strip_blank(blines))
        elif g in dupes:
            return None, [f"reply has more than one '## {g}'"], reply
    missing = [g for g in dupes if g not in merged]
    if missing:
        return None, [f"reply lacks: {', '.join(missing)}"], reply
    out_text = "\n".join("\n".join([h] + b) for h, b in merged.values())
    lost_c = sorted(c for c in cites if c not in out_text)
    lost_l = sorted(l for l in links if l not in out_text)
    if lost_c or lost_l:
        return None, [f"reply dropped citations: {lost_c[:5]}" if lost_c else "", f"reply dropped links: {lost_l[:5]}" if lost_l else ""], reply

    # splice: merged block at the first copy's position, other copies removed
    first = {g: idx[0] for g, idx in dupes.items()}
    drop = {i for idx in dupes.values() for i in idx[1:]}
    out = []
    if h2s[0][1]:
        out.append("\n".join(reflow.strip_blank(h2s[0][1])))
    for i, (head, blines) in enumerate(h2s[1:], 1):
        if i in drop:
            continue
        g = next((g for g, f in first.items() if f == i), None)
        if g:
            head, blines = merged[g]
        out.append("\n".join([head] + ([""] + reflow.strip_blank(blines) if reflow.strip_blank(blines) else [])))
    notes = [f"{g}: {len(idx)} copies -> 1" for g, idx in dupes.items()]
    notes.append(f"{len(cites)} citations and {len(links)} links all present")
    return fm + "\n\n".join(out) + "\n", notes, reply


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pages", nargs="+")
    ap.add_argument("--out", help="dry-run: write merged copies here")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--model", default="sonnet")
    args = ap.parse_args()

    backup = STATE_DIR / "backups" / f"merge-{date.today():%Y-%m-%d}"
    done = []
    for p in args.pages:
        path = Path(p)
        if not path.exists():
            hits = list(WIKI.glob(f"*/{p.removesuffix('.md')}.md"))
            if not hits:
                sys.exit(f"not found: {p}")
            path = hits[0]
        rel = path.relative_to(WIKI).as_posix()
        text = path.read_text(encoding="utf-8")
        try:
            new, notes, reply = merge_page(text, args.model)
        except Exception as exc:  # one bad page never stops the run
            print(f"{rel}: FAILED {type(exc).__name__}: {exc}")
            continue
        print(f"{rel}: " + "; ".join(n for n in notes if n), flush=True)
        if new is None:
            if reply and args.out:
                Path(args.out).mkdir(parents=True, exist_ok=True)
                (Path(args.out) / (path.stem + ".rejected-reply.md")).write_text(reply, encoding="utf-8")
            continue
        if args.out:
            dst = Path(args.out) / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(new, encoding="utf-8")
        if args.write:
            dst = backup / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dst)
            path.write_text(new, encoding="utf-8")
            done.append(path)
    if args.write and done:
        with (WIKI / "log.md").open("a", encoding="utf-8") as f:
            f.write(f"\n**merge | duplicate sections merged on {len(done)} page(s)**\n\n"
                    f"`rekall/scripts/wiki-merge-dupes.py` ({args.model}) merged adjacent duplicate State / Next steps / Members / "
                    f"Related pages sections into one each; every citation and wikilink from the inputs verified present. "
                    f"Originals in `{backup}`. Pages: {', '.join(f'[[{p.stem}]]' for p in done)}. Source: wiki-merge-dupes.py run {date.today()}.\n")
        print(f"backups in {backup}; log.md entry appended")


if __name__ == "__main__":
    main()
