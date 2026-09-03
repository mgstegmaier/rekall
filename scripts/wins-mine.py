#!/usr/bin/env python3
"""Mine a review year's evidence into one markdown dump for drafting the wins page.

Sources, all local: commits by Mike in the Upland repos, Claude Code prompt history
for work projects, wiki project pages tagged `upland`, meeting-note titles, and any
`### Wins` bullets the session digest has written into memory/sessions/.

    python3 wins-mine.py --since 2025-09-01 > /tmp/wins-evidence.md

Output is evidence, not the page. A Claude session reads it and drafts
wiki/entities/annual-review-2026-accomplishments.md from it.
"""
import argparse
import json
import re
import subprocess
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rekall_config import VAULT, WIKI  # noqa: E402

HOME = Path.home()
REPOS_DIR = HOME / "github_repos" / "Upland Repos"
HISTORY = HOME / ".claude" / "history.jsonl"
AUTHOR = "Stegmaier"
WORK_PATH_MARKERS = ("Upland", "UCG", "OneDrive", "snowflake")


def commits(since):
    by_month = defaultdict(lambda: defaultdict(list))
    for repo in sorted(REPOS_DIR.iterdir()):
        if not (repo / ".git").is_dir():
            continue
        out = subprocess.run(
            ["git", "-C", str(repo), "log", f"--author={AUTHOR}", f"--since={since}",
             "--no-merges", "--format=%ad\t%s", "--date=short"],
            capture_output=True, text=True).stdout
        for line in out.splitlines():
            date, _, subject = line.partition("\t")
            by_month[date[:7]][repo.name].append(f"{date} {subject}")
    return by_month


def prompts(since, cap):
    since_ms = datetime.strptime(since, "%Y-%m-%d").timestamp() * 1000
    by_month = defaultdict(list)
    seen = set()
    for raw in HISTORY.open(encoding="utf-8", errors="replace"):
        try:
            d = json.loads(raw)
        except ValueError:
            continue
        if d.get("timestamp", 0) < since_ms:
            continue
        proj = d.get("project", "")
        if not any(m in proj for m in WORK_PATH_MARKERS):
            continue
        text = " ".join(d.get("display", "").split())
        if len(text) < 60 or text.startswith("/") or text in seen:
            continue
        seen.add(text)
        ts = datetime.fromtimestamp(d["timestamp"] / 1000)
        by_month[ts.strftime("%Y-%m")].append((ts, Path(proj).name, text[:400]))
    # ponytail: keep the longest N per month; long prompts carry the intent, short ones are steering
    for m, items in by_month.items():
        items.sort(key=lambda t: -len(t[2]))
        by_month[m] = sorted(items[:cap])
    return by_month


def frontmatter(text):
    m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    return m.group(1) if m else ""


def project_pages():
    pages = []
    for f in sorted((WIKI / "projects").glob("*.md")):
        text = f.read_text(errors="ignore")
        fm = frontmatter(text)
        if "upland" not in fm:
            continue
        desc = re.search(r"^description:\s*(.*)$", fm, re.M)
        state = re.search(r"^## State\n(.*?)(?=^## |\Z)", text, re.M | re.DOTALL)
        pages.append((f.stem, desc.group(1) if desc else "", (state.group(1).strip() if state else "")[:2500]))
    return pages


def meetings(since):
    by_month = defaultdict(list)
    for f in sorted((WIKI / "meetings").glob("*.md")):
        if re.match(r"\d{4}-\d{2}-\d{2}", f.stem) and f.stem[:10] >= since:
            by_month[f.stem[:7]].append(f.stem)
    return by_month


def digest_wins():
    found = []
    sessions = VAULT / "memory" / "sessions"
    if not sessions.is_dir():
        return found
    for f in sorted(sessions.glob("*.md")):
        for block in re.findall(r"^### Wins\n(.*?)(?=^### |^## |\Z)", f.read_text(errors="ignore"), re.M | re.DOTALL):
            found += [f"{f.stem} {b.strip()}" for b in block.strip().splitlines() if b.strip().startswith("-")]
    return found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2025-09-01")
    ap.add_argument("--prompts-per-month", type=int, default=40)
    a = ap.parse_args()

    print(f"# Wins evidence since {a.since}\n")

    print("## Commits by month (author: Stegmaier, Upland repos)\n")
    for month, repos in sorted(commits(a.since).items()):
        print(f"### {month}")
        for repo, lines in sorted(repos.items()):
            print(f"**{repo}** ({len(lines)})")
            print("\n".join(f"- {l}" for l in lines))
        print()

    print("## Prompts by month (work projects, longest first)\n")
    for month, items in sorted(prompts(a.since, a.prompts_per_month).items()):
        print(f"### {month} ({len(items)} shown)")
        for ts, proj, text in items:
            print(f"- {ts:%Y-%m-%d} [{proj}] {text}")
        print()

    print("## Wiki project pages tagged upland\n")
    for stem, desc, state in project_pages():
        print(f"### [[{stem}]]\n{desc}\n\n{state}\n")

    print("## Meetings by month\n")
    for month, names in sorted(meetings(a.since).items()):
        print(f"### {month} ({len(names)})")
        print("\n".join(f"- [[{n}]]" for n in names))
        print()

    wins = digest_wins()
    print(f"## Session digest wins ({len(wins)})\n")
    print("\n".join(f"- {w}" for w in wins))


if __name__ == "__main__":
    main()
