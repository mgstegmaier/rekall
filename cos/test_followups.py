"""The one check: every note format the harvester claims to read, and the owner filter.

Run: cd cos && python3 test_followups.py
Needs rekall.toml with [cos] me/tracked; the fixture uses "Michael" and "Matt".
"""
from datetime import date

import followups as f

# GitHub stubbed: one PR of mine waiting on review, one review owed
f.gh.open_prs = lambda orgs, today=None: [{"number": 573, "title": "feat: snapshots", "url": "https://gh/r/pull/573", "repo": "dbtCloud",
                                              "full_repo": "Org/dbtCloud", "opened": "2026-08-26", "review": "REVIEW_REQUIRED", "wait_bdays": 8}]
f.gh.review_requests = lambda orgs: [{"number": 9, "title": "someone's PR", "url": "https://gh/r/pull/9", "repo": "Snowflake",
                                          "full_repo": "Org/Snowflake", "author": "coworker", "updated": "2026-09-05"}]

NOTE = """---
type: meeting
date: 2026-09-02
---
# Sample

## Summary

- Michael to ignore this, it is the summary

## Action Items

### Mine
- [ ] Raise character limit; share cost/perf impact w/ Charles
- [x] Review the review-queue doc

### Others
- Charles Anyanwu: Add clause to Fleet/Carrier Limit fields
- Matt Brink: Enroll in Snowflake GenAI training

## Next Steps

- [**Michael:** Review the `review queue` document.](https://fathom.video/x?t=1)
- [**Charles:** Implement fixes.](https://fathom.video/x?t=2)
- **Draft a 30/60/90 day AI enablement plan** (Michael)
- **Schedule three-way alignment meeting with Blaisdell**
- Michael to get his wiki demo presentable
  - Jeff's point: won't get it until he uses it
- Jeff to read the blog post
  - [**Matt:**](https://fathom.video/x?t=3)
      - [Clarify the gold-cutover timeline with Brent.](https://fathom.video/x?t=4)
  - [**David Sgrignoli:**](https://fathom.video/x?t=5)
      - [Analyze aggregate structures.](https://fathom.video/x?t=6)

## Related pages
- Michael: not an action, wrong section
"""

rows = list(f.parse_note(NOTE))
got = {(o, t, d) for o, t, d, _ in rows}
expected = {
    ("me", "Raise character limit; share cost/perf impact w/ Charles", False),
    ("me", "Review the review-queue doc", True),
    ("Matt Brink", "Enroll in Snowflake GenAI training", False),
    ("me", "Review the `review queue` document.", False),
    ("me", "Draft a 30/60/90 day AI enablement plan", False),
    ("me", "Michael to get his wiki demo presentable", False),
    ("Matt Brink", "Clarify the gold-cutover timeline with Brent.", False),
}
assert got == expected, f"\nmissing: {expected - got}\nextra: {got - expected}"
assert all(src.startswith("-") for *_, src in rows), "every row quotes its source line"

# owner filter
assert f.owner_of("Michael") == "me" and f.owner_of("Matthew Brink") == "Matt Brink"
assert f.owner_of("Charles Anyanwu") is None and f.owner_of("") is None

# business days: Fri 2026-09-04 -> Mon 2026-09-07 is one business day
assert f.bdays_between(date(2026, 9, 4), date(2026, 9, 7)) == 1
assert f.bdays_between(date(2026, 9, 7), date(2026, 9, 7)) == 0

# ids are stable across re-harvest and differ by source
assert f.row_id("a.md", "Do X") == f.row_id("a.md", "do x") != f.row_id("b.md", "Do X")

# checkbox sync: [x] -> done, [-] -> dropped, untouched stays open, unknown ids ignored
import tempfile
from pathlib import Path
led = {"rows": {
    "aaaaaaaaaaaa": {"status": "open", "closed": None},
    "bbbbbbbbbbbb": {"status": "open", "closed": None},
    "cccccccccccc": {"status": "open", "closed": None},
}}
block = "\n".join([f.BLOCK_START, "- [x] one · 3bd · `aaaaaaaaaaaa` · [[n]]", "- [-] two · 3bd · `bbbbbbbbbbbb` · [[n]]",
                    "- [ ] three · 3bd · `cccccccccccc` · [[n]]", "- [x] ghost · 1bd · `dddddddddddd` · [[n]]", f.BLOCK_END])
with tempfile.TemporaryDirectory() as d:
    f.TODAY_NOTE = Path(d) / "today.md"
    f.TODAY_NOTE.write_text("# Today\n\n" + block + "\n")
    assert f.sync_today(led, date(2026, 9, 7)) == 2
assert led["rows"]["aaaaaaaaaaaa"]["status"] == "done"
assert led["rows"]["bbbbbbbbbbbb"]["status"] == "dropped"
assert led["rows"]["cccccccccccc"]["status"] == "open"

# waiting_on: Monday On Hold items pass through; a blind feed gives an empty bucket plus one error, never a blind ledger
FAKE = {"status": "ok", "errors": [], "on_hold": [
    {"id": "1", "name": "Vendor SFTP creds", "url": "https://m/1", "project": "EDP", "mine": True,
     "business_days_idle": 7, "checkin_due": True, "last_comment": "asked Brent"},
    {"id": "2", "name": "Sapiens export", "url": "https://m/2", "project": None, "mine": False,
     "business_days_idle": 2, "checkin_due": False, "last_comment": None},
]}
BLIND = {"status": "blind", "errors": [{"source": "monday", "message": "HTTPError: 401"}], "on_hold": []}
with tempfile.TemporaryDirectory() as d:
    for fake, tag in ((FAKE, "ok"), (BLIND, "blind")):
        f.COS_MONDAY_SNAPSHOT = Path(d) / f"{tag}.py"
        f.COS_MONDAY_SNAPSHOT.write_text(f"import json; print(json.dumps({fake!r}))")
        snap = f.snapshot({"rows": {}}, date(2026, 9, 7), [])
        block = f.render_block(snap)
        if tag == "ok":
            assert snap["waiting_on"] == {"found": 2, "items": FAKE["on_hold"]} and snap["errors"] == []
            assert "**Waiting on (3)**" in block and block.index("Waiting on") < block.index("Closed this week")
            assert '- Vendor SFTP creds · EDP · 7 business days on hold · "asked Brent" · [link](https://m/1) · check in' in block
            assert "- Sapiens export · no project · 2 business days on hold · [link](https://m/2) · not yours" in block
        else:
            assert snap["waiting_on"] == {"found": 0, "items": []} and snap["status"] == "ok"
            assert snap["errors"] == ["waiting_on: monday snapshot blind: HTTPError: 401"]
            assert "Waiting on is blind: monday snapshot blind: HTTPError: 401" in block
    f.COS_MONDAY_SNAPSHOT = Path(d) / "gone.py"
    snap = f.snapshot({"rows": {}}, date(2026, 9, 7), [])
    assert snap["waiting_on"]["found"] == 0 and len(snap["errors"]) == 1 and "missing" in snap["errors"][0]
assert not any("`" in l for l in block.splitlines() if l.startswith("- ") and "Waiting" not in l), "no ids on Monday lines"

print(f"ok: {len(rows)} rows parsed, owner filter, aging, checkbox sync, and waiting_on passthrough hold")
