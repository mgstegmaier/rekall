---
adr: 1
title: Keep each session's opening and end under one 40,000-character budget, instead of the last 30 turns
date: 2026-10-31
status: DECIDED
decider: mgstegmaier
recorded_by: Claude Code, in the session-digest-sweep session
ticket:
validation_by: 2026-11-15
decided: 2026-10-31, session-digest-sweep chat session
reversible: yes
---

# ADR-001: Keep each session's opening and end under one 40,000-character budget, instead of the last 30 turns

## Summary

**Where it stands.** The change is decided and ships with continuation digests
(`docs/plans/2026-10-31-incremental-digests/continuation-digests.md`), not on its own. Keeping each
session's opening makes every repeat entry for a session restate that opening, so the budget lands
in the same build as the entries that record only what changed. Until that build merges, the live
digest still uses the old limits.

### The problem

A session digest is a short written summary of one Claude Code session that rekall adds to the
wiki when the session closes. A model writes it from a trimmed copy of the conversation. Two
limits did the trimming, and both cut from the front: the digest read only the last 30 turns,
then only the last 15,000 characters of those. The front of a session is where you say what you
are trying to do, so the digest lost the goal and kept the wrap-up. In 375 sessions from the two
weeks before 2026-10-31, at least 163 lost their opening this way. Nobody had recorded why the
limit was 30 turns.

### The recommendation

Drop the turn limit and keep one character budget, raised from 15,000 to 40,000 characters. A
conversation that fits goes through whole, which covers 312 of the 375 sessions. A longer one
keeps its first quarter of the budget, where the goal is, then fills the rest from the end, with
a marker in between saying how many turns were left out. The cost is model input. An average
digest now reads about 18,000 characters (roughly 4,600 tokens), against a ceiling of 15,000
characters (roughly 3,750 tokens) before. The largest digests read up to 40,000 characters
(roughly 10,000 tokens).

### Other options

| Option | Trade-off |
|---|---|
| Raise the turn limit, still keeping only the end | It changes one number, but any session over the character limit still loses its opening. |
| Head and end at the old 15,000 characters | It costs no extra tokens, but only 184 of the 375 sessions fit whole, against 312 at 40,000. |
| Send the whole conversation, no limit | Nothing is lost, but the largest session in the sample ran 235,619 characters, and one such session costs as much as about 13 average ones. |
| Do nothing | It costs nothing, and at least 163 of 375 digests keep missing why the session happened. |

### Decision needed

Nothing open.

## Detail

### The decision check (answer all five before ratifying)

1. Is the option of waiting or doing nothing on the table? Yes, as option E. Waiting keeps the
   front-cut on every long session.
2. Have the facts changed since the current plan was made? The 30-turn limit came in with the
   repo's single-commit history on 2026-09-03 (`151384a`), when the public repo was started
   fresh with no earlier history, and no reason for it is recorded. The 2026-10-31 sweep plan
   (`docs/plans/2026-10-31-session-digest-sweep.md`) kept the turn limit and proposed a
   first-5-plus-last-25 split. Measuring real sessions showed the character limit does most of
   the cutting, so a turn-based split fixes the wrong limit.
3. Is every option priced? In characters and tokens, yes. There's no dollar figure because the
   digest calls the signed-in `claude` CLI (`distil.ask()`), so the spend is plan usage rather
   than a per-call bill.
4. Whose decision is this? The repo owner's, approved in chat on 2026-10-31.
5. What check, on what date, tells us whether the decision was right? See Consequences and
   check, two weeks after the continuation-digests PR merges.

### Context

`graph-memory/digest/session_end.py` builds the digest input in `filtered()`. Before this change
it took `turns(transcript)[-max_turns:]` with `max_turns: 30`, joined them, and if the text ran
over `max_chars: 15000`, it kept the last 15,000 characters and advanced to the next whole turn.

On 2026-10-31 we measured the sessions whose transcript file changed in the 14 days before
2026-10-31, counting only sessions someone typed into (headless `claude -p` runs and test
harnesses excluded) that had 5 or more turns, the digest's
`min_turns`. That gave 375 sessions.

- 163 of the 375 had more than 30 turns, so the turn limit dropped their opening.
- For 123 of those 163, the last 30 turns alone ran over 15,000 characters, so the character
  limit cut them again.
- The median full conversation is 15,413 characters, the 95th percentile is 72,035, and the
  largest is 235,619.
- Full conversations of 15,000 characters or fewer: 184 of 375. Of 40,000 or fewer: 312 of 375.

Token figures in this ADR use roughly 4 characters per token for English text. The digest
prompt itself adds a fixed amount on top of every call, so it doesn't change the comparison.

### Options

| Option | Gains | Costs and risks | Priced? |
|---|---|---|---|
| A. Head and end under one 40,000-character budget (chosen) | 312 of 375 sessions go through whole. The rest keep their opening (the first quarter of the budget) and their end. One limit to reason about. | Average input rises to about 18,400 characters (about 4,600 tokens). The ceiling rises from about 3,750 to about 10,000 tokens. The middle of a very long session is still dropped. | Yes, in tokens |
| B. Raise `max_turns`, keep the tail-only cut | One-line change. | Any session over the character limit still loses its opening. The character limit, not the turn limit, did the cutting for 123 of the 163 long sessions. | Yes, no extra cost at 15,000 |
| C. Head and end at 15,000 characters | No extra tokens. Long sessions keep their opening. | Only 184 of 375 go through whole, and the 191 others are split. The split leaves 3,750 characters for the opening and about 11,000 for the end. | Yes, no extra cost |
| D. No limit, send everything | Nothing is lost. | The largest session (235,619 characters, about 59,000 tokens) costs about 13 times an average digest. Very long inputs may also give vaguer entries, and the sample doesn't show that one way or the other. | Partly: tokens yes, entry quality no |
| E. Do nothing | No work. | At least 163 of 375 digests keep missing the session's goal. | Yes |

### Decision

Option A. It puts the limit where the cutting happens (characters), keeps the session's goal in
every digest, and sends most sessions through whole, for an average input of about 18,400
characters against a 15,000-character ceiling before. The first-quarter share for the opening is a judgment call, and the code marks it
with a `ponytail:` comment, so a later change only touches one line.

### Consequences and check

What we now own:

- `max_turns` is gone from `digest/common.py` defaults and `digest/config.json`. A local
  `config.json` that still sets it is ignored.
- `filtered()` reserves 40 characters for the `[... N turns omitted ...]` marker. It clips any
  single turn longer than a quarter of the budget (a pasted file, say), so the opening and the
  end each keep at least one turn.
- `graph-memory/test_digest_filter.py` covers the whole-fit case, the split, and the clipped
  oversized turn.

The check, two weeks after the continuation-digests PR merges: read the digest entries written since the merge, and pick five whose
sessions were over 40,000 characters. Each one should state the session's goal from its opening
turns. Count failures in `digest/log/digest.log`, where every attempt writes one line tagged `digest ok`,
`digest dropped <reason>` or `digest failed <exception>`: report `digest failed` over all three for the two weeks
before and the two weeks after the merge, since larger inputs could raise timeouts. Lines from
before the outcome tags shipped carry no tag, so take the "before" rate from the log's untagged failure
lines (`headless_run:` or `drain:` lines ending in an exception name) over the sessions digested then. If entries got vaguer or
failures rose, lower `max_chars` in `digest/config.json`. That change needs no code.

## Changes

- 2026-10-31: proposed and decided in the same session. Built on `claude/session-digest-sweep-aaad6e`.
- 2026-11-01: ships with continuation digests rather than alone. The check date is two weeks after
  that PR merges; `validation_by` is set in a follow-up commit once the merge date is known.
- 2026-11-01: continuation digests merged as PR #34 (`8b69e2a`); `validation_by` set to 2026-11-15.
