---
name: prep
description: Meeting prep from the wiki. Use when the user says /prep, "prep me for X", "what's the context for my next meeting", "brief me on the 2pm", or a new meeting appeared on the calendar. Runs cos/prep.py (read-only calendar plus wiki lookups) and writes the brief block into today.md; optionally adds a short narration on top.
---

# Prep

`cos/prep.py` does the work. It reads today's calendar (Microsoft Graph, read scopes only), finds
the thread each meeting belongs to in the wiki, and writes one marker block into `today.md`. This
skill runs it and, when you're in a conversation, says the three things worth knowing.

```bash
python3 ~/github_repos/personal_projects/rekall/cos/prep.py            # every meeting today
python3 ~/github_repos/personal_projects/rekall/cos/prep.py next       # the next one only
python3 ~/github_repos/personal_projects/rekall/cos/prep.py "Zane"     # subject contains text
python3 ~/github_repos/personal_projects/rekall/cos/prep.py --json     # facts, no write
python3 ~/github_repos/personal_projects/rekall/cos/prep.py --date 2026-09-04   # preview a past day, prints, never writes
```

Run it in the foreground with a 5 minute timeout. It takes 10 to 30 seconds; the Monday snapshot
is the slow part.

## What the block holds, per meeting

Two short lists, nothing else (Mike, 2026-09-07: no attendee list, no person pages, no recall hits).

- **Bring**: to-dos from the prior notes that became Monday tickets, with status; what you still
  owe the people in the room, from any meeting; a tracked person's open items when they're present;
  unanswered questions from last time. "Nothing tracked." when empty.
- **Background**: the project page's State in two sentences; the last meeting, how long ago, and
  its one-line summary; what changed on the project page since then; the line in a recent note that
  spawned this meeting when there is one. The invite text appears only when no earlier note exists.

## In conversation

After the script runs, read the block for the meeting asked about and answer in at most five
lines: what this meeting is a continuation of, what is still open from last time, and the one
thing to bring. Quote the source note for anything you assert. If the block says "no parent
found", say so; don't invent a lineage.

## Rules

- Reads only. Never write to the calendar, mail, or Teams (Mike, 2026-09-07).
- `today.md` is the only file written, and only the `<!-- cos-prep -->` block in it.
- If the script prints "Prep is blind", relay the reason. Don't reconstruct a brief by hand.
