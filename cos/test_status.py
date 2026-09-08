"""The one check for status.py: bucket counts, wins dedup, the blind line, heading order.

Run: cd cos && python3 test_status.py
No network: the Monday snapshot is stubbed blind. Needs rekall.toml (any values).
"""
import json
import tempfile
from datetime import date
from pathlib import Path

import followups as f
import status as s

# GitHub is stubbed: one merged PR in the window, one open PR waiting on review, no review requests.
s.gh.merged_prs = lambda since, orgs: [{"number": 12, "title": "fix(x): one merged thing", "url": "https://gh/x/pull/12",
                                          "repo": "Repo", "full_repo": "Org/Repo", "date": "2026-09-03"}]
s.gh.open_prs = lambda orgs, today=None: [{"number": 13, "title": "feat(y): waiting thing", "url": "https://gh/y/pull/13",
                                              "repo": "Repo", "full_repo": "Org/Repo", "opened": "2026-08-20",
                                              "review": "REVIEW_REQUIRED", "wait_bdays": 9}]
s.gh.review_requests = lambda orgs: []
s.gh.pr_files = lambda url: []
s.projects.project_repos = lambda: {}  # no repos: mapping in the fixture vault; PRs label by repo

DIGEST = """
## Session 09:00

### What happened
Read things. Nothing shipped.

## Session 10:30

### What happened
Shipped two things.

### Decisions
- Keep the ledger as one JSON file.
- Cap decisions at ten.

### Wins
- Astronomer test suite unblocked: 168 passing.
- Gap ticket filed for the missing column.
"""

PAGE = """---
type: project
title: Sample
---
# Sample

## Updates

### 2026-09-03 Recall hook reviewed; graph leg stays as-is
Measured ten queries [link](https://x). Second sentence is not wanted.

### 2026-08-20 Old entry
Out of the window.
"""

WINS = """# Wins

## Running log (auto)
- 2026-09-03 Astronomer test suite unblocked: 168 passing. (source: wiki/sessions/2026-09-03.md)
- 2026-09-02 Annual-review evidence pipeline shipped. (source: memory/sessions/2026-09-02.md)
- 2026-08-25 Old win. (source: wiki/sessions/2026-08-25.md)
"""

LEDGER = {"rows": {
    "a" * 12: {"id": "a" * 12, "owner": "me", "text": "Send Jeff the charter", "status": "open", "opened": "2026-09-01",
               "source": "wiki/meetings/2026-09-01-1-1-gottlieb-stegmaier.md"},
    "b" * 12: {"id": "b" * 12, "owner": "me", "text": "Not a 1:1", "status": "open", "opened": "2026-09-01",
               "source": "wiki/meetings/2026-09-01-de-team-sync.md"},
    "c" * 12: {"id": "c" * 12, "owner": "Matt Brink", "text": "Matt's item", "status": "open", "opened": "2026-09-01",
               "source": "wiki/meetings/2026-09-01-1-1-gottlieb-stegmaier.md"},
    "d" * 12: {"id": "d" * 12, "owner": "me", "text": "Done already", "status": "done", "opened": "2026-09-01",
               "source": "wiki/meetings/2026-09-01-1-1-gottlieb-stegmaier.md"},
}}

with tempfile.TemporaryDirectory() as d:
    root = Path(d)
    (root / "wiki" / "sessions").mkdir(parents=True)
    (root / "wiki" / "pages").mkdir()
    (root / "wiki" / "sessions" / "2026-09-03.md").write_text(DIGEST)
    (root / "wiki" / "sessions" / "2026-08-20.md").write_text(DIGEST.replace("Shipped two", "old"))
    (root / "wiki" / "pages" / "sample.md").write_text(PAGE)
    (root / "wiki" / "pages" / "wins.md").write_text(WINS)
    (root / "follow-ups.json").write_text(json.dumps(LEDGER))
    s.SESSIONS = root / "wiki" / "sessions"
    s.PAGES = root / "wiki" / "pages"
    s.WINS_PAGE = root / "wiki" / "pages" / "wins.md"
    s.TODAY_NOTE = root / "today.md"
    s.AUDIENCE = "Jeff Gottlieb"
    f.LEDGER = root / "follow-ups.json"
    s.monday = lambda: (None, "stubbed: no token")

    start, end = s.window(date(2026, 9, 7))
    assert (start, end) == (date(2026, 9, 1), date(2026, 9, 7))
    assert s.window(None, date(2026, 9, 3)) == (date(2026, 8, 31), date(2026, 9, 6))
    snap = s.snapshot(start, end, date(2026, 9, 7))

    # shipped: two digest wins + one wins-page row; the duplicate row and the old one are dropped
    assert snap["shipped"]["found"] == 4, snap["shipped"]
    texts = [i["text"] for i in snap["shipped"]["items"]]
    assert texts.count("Astronomer test suite unblocked: 168 passing.") == 1, "dedup by normalized text"
    assert "Annual-review evidence pipeline shipped." in texts
    assert snap["shipped"]["items"][1]["session"] == "Session 10:30"

    assert snap["in_flight"]["found"] == 1
    fl = snap["in_flight"]["items"][0]
    assert fl["page"] == "sample" and fl["heading"] == "Recall hook reviewed; graph leg stays as-is"
    assert fl["first_sentence"] == "Measured ten queries link."

    assert snap["blocked"]["found"] == 1
    assert snap["owed"]["found"] == 1 and snap["owed"]["items"][0]["text"] == "Send Jeff the charter"
    assert snap["owed"]["items"][0]["age_bdays"] == 4  # Tue 09-01 -> Mon 09-07
    assert snap["decisions"]["found"] == 2 and snap["decisions"]["items"][0]["text"] == "Cap decisions at ten."
    assert snap["errors"] == ["shipped: monday: stubbed: no token", "blocked: monday: stubbed: no token"]
    assert snap["status"] == "ok"

    block = s.render_block(snap)
    heads = ["**In flight (1)**", "**Blocked (1)**", "**You owe (1)**", "**Decisions this week (2)**", "**PRs not linked (1)**", "**Shipped (4)**"]
    assert "[#12](https://gh/x/pull/12) fix(x): one merged thing [missing: wiki page]" in block, "Monday is blind here, so only the wiki check runs"
    pos = [block.index(h) for h in heads]
    assert pos == sorted(pos), block
    assert "**Blocked (1)**\nmonday is blind: stubbed: no token\n" in block, block
    assert block.endswith("_Facts by cos/status.py · draft the message with /status_\n" + s.BLOCK_END)

    # write, then rewrite: one block, other text untouched
    s.TODAY_NOTE.write_text("# Today\n\nkeep me\n")
    s.write_today(block)
    s.write_today(block)
    t = s.TODAY_NOTE.read_text()
    assert t.count(s.BLOCK_START) == 1 and "keep me" in t

    # every source missing: blind, no exception
    s.SESSIONS, s.PAGES, s.WINS_PAGE = root / "nope", root / "nope", root / "nope.md"
    f.LEDGER = root / "nope.json"
    def down(*a, **k):
        raise RuntimeError("gh is not installed")
    s.gh.merged_prs = s.gh.open_prs = s.gh.review_requests = down
    empty = s.snapshot(start, end, date(2026, 9, 7))
    assert empty["status"] == "blind" and len(empty["errors"]) == 9, empty["errors"]  # 5 vault/Monday + 3 GitHub + 1 rigor pages

assert "[#12](https://gh/x/pull/12) fix(x): one merged thing" in block and "**Repo** · [#13]" in block, "PR numbers render"
print("ok: buckets, wins dedup, blind line, heading order, block rewrite, PR numbers hold")
