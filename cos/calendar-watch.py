#!/usr/bin/env python3
"""Calendar watch: when a meeting appears, moves, or gains people, prep it and say so.

Runs every 15 minutes from launchd. Fetches today's calendar (read-only), compares
each two-or-more-person event's title, start, and attendees against the last run's
cache, and when anything changed runs cos/prep.py and posts one macOS notification
per changed meeting. On a quiet run it fetches, compares, and exits: no Claude, no
prep, nothing written.

First run of a new day seeds the cache and runs prep once without notifying, so a
laptop that wakes at 9 still gets today's briefs without a burst of alerts.

  calendar-watch.py            the scheduled run
  calendar-watch.py --dry-run  report what changed, don't prep or notify

Cache: STATE_DIR/calendar-cache.json.
"""
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prep  # noqa: E402

CACHE = prep.STATE_DIR / "calendar-cache.json"
PREP = Path(__file__).resolve().parent / "prep.py"


def signature(ev):
    return {"title": ev["title"], "start": ev["start"], "attendees": ev["attendees"]}


def diff(old, new):
    """(added, changed, removed) event ids between two {id: signature} maps."""
    added = [i for i in new if i not in old]
    changed = [i for i in new if i in old and old[i] != new[i]]
    removed = [i for i in old if i not in new]
    return added, changed, removed


def main(argv):
    dry = "--dry-run" in argv
    today = date.today().isoformat()
    try:
        events = prep.fetch_events(date.today())
    except Exception as e:
        prep.log(f"calendar unavailable: {e}")
        return 0  # a blind poll is not an error worth a notification every 15 minutes
    now = {e["id"]: signature(e) for e in events}
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    fresh_day = cache.get("day") != today
    added, changed, removed = diff({} if fresh_day else cache.get("events", {}), now)
    if not dry:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps({"day": today, "events": now}, indent=1))
    if fresh_day:
        prep.log(f"new day, {len(now)} meeting(s) seeded" + ("" if dry else "; running prep quietly"))
        if not dry:
            subprocess.run(["python3", str(PREP)], capture_output=True, text=True, timeout=300)
        return 0
    if not (added or changed or removed):
        prep.log("no change")
        return 0
    prep.log(f"added {len(added)}, changed {len(changed)}, removed {len(removed)}")
    if dry:
        for i in added + changed:
            print(f"{'new' if i in added else 'changed'}: {now[i]['start']} {now[i]['title']}")
        return 0
    run = subprocess.run(["python3", str(PREP)], capture_output=True, text=True, timeout=300)
    prep.log(run.stdout.strip() or run.stderr.strip()[-200:])
    for i in added:
        prep.fp.notify(f"Prep ready: {now[i]['title']} at {now[i]['start']}", title="Meeting prep")
    for i in changed:
        prep.fp.notify(f"Re-prepped: {now[i]['title']} at {now[i]['start']} (meeting changed)", title="Meeting prep")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
