---
name: status
description: Friday status draft from the wiki. Use when the user says /status, "draft my status update", "weekly update for Jeff", "what did I ship this week", or the Friday launchd job runs it headless. Runs cos/status.py (session digests, wins page, project pages, Monday, follow-ups ledger) to write the week's facts into today.md, then drafts the Teams message under them.
---

# Status

`cos/status.py` does the fact-finding. It reads this week's session digests, the wins page,
project pages, the Monday board snapshot, and the follow-ups ledger, and writes one marker block
of facts into `today.md`. This skill runs it, then writes the draft message under the facts.

```bash
python3 ~/github_repos/personal_projects/rekall/cos/status.py render                       # this week -> today.md block
python3 ~/github_repos/personal_projects/rekall/cos/status.py                              # facts as JSON, no write
python3 ~/github_repos/personal_projects/rekall/cos/status.py render --week-of 2026-09-01  # another week, prints, never writes
```

Run it in the foreground with a 120 second timeout. The Monday pull is the slow part.

## What the block holds

Five headings, always in this order, each with its count: Shipped, In flight, Blocked, You owe
Jeff, Decisions this week. Every bullet ends with its source in brackets. An empty bucket shows
"(0)" and nothing under it. A source that failed shows one line, "X is blind: reason", under
its heading. The footer is `_Facts by cos/status.py · draft the message with /status_`.

## Write the draft

1. Read the `<!-- cos-status:start -->` block in `today.md` (path: `python3 ~/github_repos/personal_projects/rekall/rekall_config.py VAULT`, then `today.md` in that folder).
2. Write the draft inside the same block, between a line `**Draft**` and the footer. Use Edit; touch nothing outside the block.
3. Stop. Print nothing else when running headless.

The draft is 6 to 10 lines of plain text that survives the Teams compose box: no tables, no
headers, no bullets, no backticks. Bold only the four labels, and only these four: **Shipped**,
**In flight**, **Blocked**, **Need from you**. Each label starts its own line. Write in first
person. Shipped is past tense. One concrete ask at most, under Need from you; if there is
nothing to ask, that line says so in a few words. Cite nothing in the draft; the facts above it
carry the sources.

## Shipped means merged

Merged PRs are the authoritative Shipped for the audience, and every PR line carries its number and
link. Session digest wins are Mike's own record; in the draft they supply the "why it mattered"
sentence for a PR, never a Shipped line of their own unless nothing shipped as a PR that week
(Mike, 2026-09-07). Open PRs read as In flight; open PRs past the review-wait threshold read as
Blocked with the days waiting; PRs where Mike's review is requested read under You owe.

## PRs not linked is for Mike, never for the draft

That bucket lists merged PRs missing a wiki project-page citation (`#N` with link) or a Monday
ticket comment carrying the PR URL. It is the rigor check on the session → ticket → PR → page chain.
Leave it out of the draft. If it has rows, say so in one line after the draft, with the fix per row:
"add #N to the <page> Updates" or "`monday_ticket.py log <state> --pr <url>`".

## Rules

- Every sentence in the draft traces to a fact line above it. Nothing invented, nothing
  remembered from elsewhere. If it isn't in the block, it isn't in the draft.
- If a heading shows "X is blind", the draft says "couldn't pull X this week" and moves on.
- The draft is a draft. Mike pastes it himself. Never send anything to Teams, mail, Monday, or the
  calendar (Mike, 2026-09-07).
- `today.md` is the only file written, and only the `<!-- cos-status -->` block in it. Do not
  update any other file, wiki page, or memory.
- If the script exits nonzero or prints nothing, stop and report the error. Don't reconstruct the
  facts by hand.
