#!/usr/bin/env python3
"""Reflow wiki pages so the current picture comes first and updates read newest-first.

Output order for a page:
  frontmatter, preamble (title, Summary, Sources, Last updated, intro prose),
  ## State, ## Next steps, ## Members  (first occurrence of each; duplicates follow it, flagged),
  ## Updates  (every leading-date section as a ### entry, newest first),
  reference sections in their original order,
  ## Related pages last.

Mechanical: sections move, text inside them does not change. A heading counts as a dated
update when it STARTS with YYYY-MM-DD. Dated H3s nested under a dated H2 become entries of
their own; dated H3s under a non-dated section are reordered newest-first in place.
Duplicate State / Next steps / Members / Related pages sections are kept adjacent and
reported: merging them is a judgement call for a Claude pass, not this script.

Usage:
  wiki-reflow.py PAGE [PAGE ...]        # dry-run: report what would move, write nothing
  wiki-reflow.py --all                  # every page under wiki/{projects,entities,concepts,people}
  wiki-reflow.py ... --out DIR          # dry-run, but write the reflowed copies into DIR
  wiki-reflow.py ... --write            # rewrite in place; originals copied to
                                        # STATE_DIR/backups/reflow-YYYY-MM-DD/; one wiki/log.md entry
Structure rules: the vault's wiki/CLAUDE.md.
"""

import argparse
import re
import shutil
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rekall_config import STATE_DIR, WIKI  # noqa: E402

DATED = re.compile(r"^(#{2,3}) +(\d{4}-\d{2}-\d{2})\b(.*)$")
# "## Connector live (2026-07-09)" or "(2026-06-10 to 2026-06-17)" or "(2026-07-13 weekly)":
# the date at the END of the heading, the other style the wiki grew before this rule
TRAILING = re.compile(r"^(#{2,3}) +(.*?)\s*\((\d{4}-\d{2}-\d{2})([^)]*)\)\s*$")
# "## State (as of 2026-02-24 — EDP Refactor Day 1)" or "## State (as of 2026-02-19) — naming":
# a dated snapshot of State, i.e. an update, not a second State section
SNAPSHOT = re.compile(r"^(#{2,3}) +State \(as of (\d{4}-\d{2}-\d{2})\s*(?:[—:-]\s*)?([^)]*)\)\s*(?:[—:-]\s*)?(.*)$")
CANON = ("State", "Next steps", "Members")


def dated(heading):
    """(date, normalized ### heading) for a dated update heading, else None.
    Leading dates keep their text; trailing dates move to the front, and a paren that held
    only the date is dropped, one that held more ("to 2026-06-17", "weekly") is kept."""
    m = DATED.match(heading)
    if m:
        return m.group(2), f"### {m.group(2)}{m.group(3)}"
    m = SNAPSHOT.match(heading)
    if m:
        rest = " — ".join(p.strip() for p in (m.group(3), m.group(4)) if p.strip())
        return m.group(2), f"### {m.group(2)} State snapshot" + (f" — {rest}" if rest else "")
    m = TRAILING.match(heading)
    if m:
        title, d, extra = m.group(2), m.group(3), m.group(4).strip()
        return d, f"### {d} {title}" + (f" ({d} {extra})" if extra else "")
    return None
FOLDERS = ("projects", "entities", "concepts", "people")


def split_frontmatter(text):
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end != -1:
            cut = text.index("\n", end + 1) + 1 if "\n" in text[end + 1:] else len(text)
            return text[:cut], text[cut:]
    return "", text


def blocks(lines, level):
    """Split lines into (heading_line|None, body_lines) at headings of exactly `level` #s,
    outside code fences. The first block has heading None (the preamble)."""
    mark = "#" * level + " "
    out, cur_head, cur = [], None, []
    fence = False
    for ln in lines:
        if ln.startswith("```"):
            fence = not fence
        if not fence and ln.startswith(mark):
            out.append((cur_head, cur))
            cur_head, cur = ln, []
        else:
            cur.append(ln)
    out.append((cur_head, cur))
    return out


def strip_blank(lines):
    while lines and not lines[0].strip():
        lines = lines[1:]
    while lines and not lines[-1].strip():
        lines = lines[:-1]
    return lines


def demote(lines):
    """One more # on every heading line outside fences (for bodies moving down a level)."""
    out, fence = [], False
    for ln in lines:
        if ln.startswith("```"):
            fence = not fence
        out.append("#" + ln if (not fence and ln.startswith("#")) else ln)
    return out


def heading_text(h):
    return h.lstrip("#").strip()


def outline(text):
    """Heading lines in order, outside code fences. Two texts with the same outline differ
    only in whitespace, and a whitespace-only rewrite is churn, not a reflow."""
    out, fence = [], False
    for ln in text.splitlines():
        if ln.startswith("```"):
            fence = not fence
        elif not fence and ln.startswith("#"):
            out.append(ln)
    return out


def entry(date_str, head, body, order):
    return {"date": date_str, "order": order, "head": head, "body": strip_blank(body)}


def reflow(text):
    """Return (new_text, notes). notes lists what moved and what needs a merge pass."""
    fm, body = split_frontmatter(text)
    h2s = blocks(body.splitlines(), 2)
    canon = {k: [] for k in CANON}
    entries, reference, related = [], [], []
    notes = []
    order = 0

    # dated H3s with no H2 above them (a page that grew a log before it grew sections)
    pre = blocks(h2s[0][1], 3)
    preamble = list(pre[0][1])
    for h3head, h3body in pre[1:]:
        d3 = dated(h3head)
        if d3:
            order += 1
            entries.append(entry(d3[0], d3[1], h3body, order))
            notes.append("moved dated subsection out of the preamble")
        else:
            preamble += [h3head] + h3body
    preamble = strip_blank(preamble)

    for head, blines in h2s[1:]:
        htxt = heading_text(head)
        d = dated(head)
        if d:
            # dated H2: its own entry, plus any dated H3 children as separate entries
            h3s = blocks(blines, 3)
            own = list(h3s[0][1])
            for h3head, h3body in h3s[1:]:
                d3 = dated(h3head)
                if d3:
                    order += 1
                    entries.append(entry(d3[0], d3[1], h3body, order))
                else:
                    own += [h3head] + h3body  # stays with its parent, one level down
            order += 1
            entries.append(entry(d[0], d[1], demote(own), order))
            continue
        if htxt == "Updates":
            # already newest-first: negative, decreasing order keeps same-day entries in place,
            # while anything appended below the page (positive order) still sorts in front of them
            for i, (h3head, h3body) in enumerate(blocks(blines, 3)[1:]):
                d3 = dated(h3head)
                if d3:
                    entries.append(entry(d3[0], d3[1], h3body, -i))
                else:
                    entries.append({"date": "0000-00-00", "order": -i, "head": h3head, "body": strip_blank(h3body)})
            continue
        if htxt in canon:
            # dated subsections filed under State/Next steps/Members are updates in the wrong place
            h3s = blocks(blines, 3)
            kept = list(h3s[0][1])
            for h3head, h3body in h3s[1:]:
                d3 = dated(h3head)
                if d3:
                    order += 1
                    entries.append(entry(d3[0], d3[1], h3body, order))
                    notes.append(f"moved dated subsection out of '{htxt}'")
                else:
                    kept += [h3head] + h3body
            canon[htxt].append((head, strip_blank(kept)))
            continue
        if htxt == "Related pages":
            related.append((head, strip_blank(blines)))
            continue
        # reference section: keep, but reorder any dated H3 children newest-first in place
        h3s = blocks(blines, 3)
        dated_idx = [i for i, (h, _) in enumerate(h3s[1:], 1) if dated(h)]
        if len(dated_idx) > 1:
            dated_sorted = sorted((h3s[i] for i in dated_idx), key=lambda hb: dated(hb[0])[0], reverse=True)
            if [h3s[i] for i in dated_idx] != dated_sorted:
                notes.append(f"reordered {len(dated_idx)} dated subsections under '{htxt}'")
                for i, hb in zip(dated_idx, dated_sorted):
                    h3s[i] = hb
        rebuilt = list(h3s[0][1])
        for h, b in h3s[1:]:
            rebuilt += [h] + b
        reference.append((head, strip_blank(rebuilt)))

    entries.sort(key=lambda e: (e["date"], e["order"]), reverse=True)

    out = []
    if preamble:
        out.append("\n".join(preamble))
    if any(canon.values()) and not entries and not notes:
        notes.append("moved State/Next steps/Members ahead of the prose")
    for k in CANON:
        for i, (head, b) in enumerate(canon[k]):
            out.append("\n".join([head] + ([""] + b if b else [])))
        if len(canon[k]) > 1:
            notes.append(f"MERGE NEEDED: {len(canon[k])} '## {k}' sections")
    if entries:
        out.append("## Updates\n\nNewest first.")
        for e in entries:
            out.append("\n".join([e["head"]] + ([""] + e["body"] if e["body"] else [])))
        notes.append(f"{len(entries)} dated entries under ## Updates")
    for head, b in reference:
        out.append("\n".join([head] + ([""] + b if b else [])))
    for head, b in related:
        out.append("\n".join([head] + ([""] + b if b else [])))
    if len(related) > 1:
        notes.append(f"MERGE NEEDED: {len(related)} '## Related pages' sections")

    return fm + "\n\n".join(out) + "\n", notes


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pages", nargs="*", help="page paths or basenames")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--out", help="dry-run: write reflowed copies here")
    ap.add_argument("--write", action="store_true", help="rewrite in place (with backups)")
    args = ap.parse_args()

    if args.all:
        paths = sorted(p for d in FOLDERS for p in (WIKI / d).glob("*.md"))
    else:
        paths = []
        for p in args.pages:
            cand = Path(p)
            if not cand.exists():
                hits = [q for d in FOLDERS for q in (WIKI / d).glob(f"{p.removesuffix('.md')}.md")]
                if not hits:
                    sys.exit(f"not found: {p}")
                cand = hits[0]
            paths.append(cand)
    if not paths:
        ap.error("give page paths or --all")

    backup = STATE_DIR / "backups" / f"reflow-{date.today():%Y-%m-%d}"
    changed, merges = [], []
    for p in paths:
        text = p.read_text(encoding="utf-8")
        new, notes = reflow(text)
        if new == text or outline(new) == outline(text):
            continue
        changed.append(p)
        rel = p.relative_to(WIKI).as_posix()
        print(f"{rel}: " + "; ".join(notes))
        if any(n.startswith("MERGE") for n in notes):
            merges.append(rel)
        if args.out:
            dst = Path(args.out) / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(new, encoding="utf-8")
        if args.write:
            dst = backup / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dst)
            p.write_text(new, encoding="utf-8")

    mode = "rewrote" if args.write else "would reflow"
    print(f"\n{mode} {len(changed)} of {len(paths)} pages; {len(merges)} need a merge pass" + (f": {', '.join(merges)}" if merges else ""))
    if args.write and changed:
        log = WIKI / "log.md"
        names = ", ".join(f"[[{p.stem}]]" for p in changed)
        with log.open("a", encoding="utf-8") as f:
            f.write(f"\n**reflow | {len(changed)} pages reordered (State, Next steps, Members first; dated updates newest-first under ## Updates)**\n\n"
                    f"Mechanical reorder by `rekall/scripts/wiki-reflow.py`; no text changed. Originals in `{backup}`. "
                    f"Pages: {names}. Needing a merge pass for duplicate sections: {', '.join(merges) or 'none'}. Source: wiki-reflow.py run {date.today()}.\n")
        print(f"backups in {backup}; log.md entry appended")


if __name__ == "__main__":
    main()
