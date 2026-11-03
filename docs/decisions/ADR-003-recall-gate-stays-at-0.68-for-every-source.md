---
adr: 3
title: Keep the recall gate at cosine 0.68 for every source, instead of raising it or holding noisy folders to a stricter floor
date: 2026-11-03
status: DECIDED
decider: mgstegmaier
recorded_by: Claude Code, in the rekall search-against-grep benchmark session
ticket:
validation_by: 2026-12-03
decided: 2026-11-03, chat in the benchmark session
reversible: yes
---

# ADR-003: Keep the recall gate at cosine 0.68 for every source, instead of raising it or holding noisy folders to a stricter floor

## Summary

**Where it stands.** Decided. No search code changed. The graded check that measured these options, `eval/judged_gate.py`, ships in the same PR, so the next proposal can be scored the same way.

### The problem

Before Claude answers a prompt, the recall hook injects up to five wiki excerpts that clear a meaning-similarity floor (the gate). On 80 real prompts with every excerpt graded by a judge, the live gate showed a relevant excerpt on 38 of the 43 prompts that had one. It also injected about 1.4 irrelevant excerpts per prompt, and it injected something on 23 of the 37 prompts that needed nothing. The noise is the obvious target, and two ways to cut it were tested.

### The recommendation

Keep the gate at 0.68 for every folder. Both stricter gates bought quiet by giving up relevant excerpts at about the same rate, and the relevant excerpt matters more. An irrelevant excerpt costs about 280 characters of a 1,500-character budget. A relevant excerpt the hook drops is one Claude almost never goes and fetches: over 60 days, Claude read a wiki page on its own after only 24 prompts. The cost of this choice is that the noise stays.

### Other options

| Option | Trade-off |
|---|---|
| B. Raise the gate to 0.70 for every folder | Cuts noise from 1.43 to 1.18 excerpts per prompt and stays quiet on 6 more empty prompts. Loses the relevant excerpt on 3 of 43 prompts; the band it removes is about half useful. |
| C. Hold session digests, meetings, raw sources and daily notes to 0.74 | Looked free on the 80 prompts it was tuned on (same usefulness, 45 percent less noise). On 40 fresh prompts it cut noise only 14 percent and lost 2 of 18 useful prompts. |
| D. Wait or do nothing | The same as the recommendation: the gate already sits at 0.68. |

### Decision needed

Nothing open.

## Detail

### The decision check (answer all five before ratifying)

1. **Is waiting or doing nothing on the table?** Yes. It's the chosen option, because the gate is already 0.68.
2. **Have the facts changed since the current plan was made?** The 0.68 floor was calibrated on 2026-09-24 against 15 named prompts and about 20 junk prompts. This is the first measurement on real prompts with graded results. It agrees with the old calibration and adds the price of each alternative.
3. **Is every option priced?** Yes. Each option below is priced in relevant excerpts lost and irrelevant excerpts removed, on the same graded prompts.
4. **Whose decision is this?** The maintainer's. He chose to keep 0.68 after seeing the 0.70 trade, and the source gate was dropped after its held-out check.
5. **What check, on what date, tells us whether this was right?** On 2026-12-03, run `eval/judged_gate.py`. The decision holds if usefulness hasn't dropped against its baseline and fewer than 20 percent of shown sections are unjudged. If irrelevant excerpts per prompt have risen above the baseline by 0.25 or more, revisit.

### Context

The measurements come from one session on 2026-11-03.

- **The prompt sample.** 80 real prompts were drawn from 60 days of interactive Claude Code sessions. Headless runs, slash commands, harness messages, and prompts under 6 or over 80 words were left out, and prompts from the rekall folder were capped at 12.
- **Pooling and grading.** Every search variant ran as of the prompt's date, with session digests and meetings dated on or after it dropped. Each variant's top 5 chunks were pooled (687 chunks), and Sonnet judges graded each chunk without knowing which variant found it: 2 directly relevant, 1 related background, 0 not useful. A spot check of 12 grades would have changed at most one.
- **The held-out set.** 40 more prompts, none from the first 80, were graded the same way to check the source gate.
- **What the gate controls.** `MEANING_THRESHOLD` in `graph-memory/recall_hook.py` sets the cosine floor. A chunk passes if its cosine clears the floor or it is a strong keyword hit.
- **Why a missed excerpt costs more.** The recall-use log shows that 2 of 5,675 injected labels were later opened with Read. Over 60 days, only 24 interactive prompts were followed by Claude reading a wiki page on its own. In practice, the injection is the only route by which the wiki reaches a session.
- **Synthetic questions mislead.** On 112 questions written from random pages, recency weighting and the gate both looked harmful. On real prompts both helped: nDCG@5 was 0.99 at the 0.9 recency floor against 0.96 with recency off. Settings in this area should be judged on real prompts.

### Options

All numbers are on the 80 judged prompts unless marked held out. "Useful" counts prompts with a grade-2 chunk in the pool that the variant shows. "Silent" counts prompts with nothing grade 2 where the variant injects nothing.

| Option | Gains | Costs and risks | Priced? |
|---|---|---|---|
| A. 0.68 for every folder (kept) | Useful on 38 of 43. Never silenced a prompt that needed something. | 1.43 irrelevant chunks per prompt; 41 percent of shown chunks graded 0; silent on only 14 of 37. | Yes |
| B. 0.70 for every folder | 1.18 irrelevant chunks per prompt; silent on 20 of 37. | Useful drops to 35 of 43. The band from 0.68 to 0.70 held 44 shown chunks: 20 graded 0, 12 graded 1, 12 graded 2. All three prompts that lost their only relevant chunk were short mid-task requests. | Yes |
| C. 0.74 for `sessions/`, `meetings/`, `raw/`, `daily-notes-archive/`, with no strong-keyword pass for them | On the 80: useful 38 of 44 (a fresh judge graded 22 newly surfaced chunks), 0.79 irrelevant per prompt, silent 21 of 36. | 0.74 was picked from three settings on those same prompts. Held out (40 prompts): useful 15 of 18 against 17 for the live gate, irrelevant 1.48 against 1.73, a 14 percent cut. Both lost prompts were operational asks whose context lived in digests or meetings. | Yes |
| D. Wait / do nothing | Same as A. | Same as A. | Yes |

On the 80 prompts, irrelevant chunks by source of what the live gate showed were: pages 11 percent, plans 34 percent, session digests 59 percent, daily notes 62 percent, raw 77 percent, meetings 79 percent. Folder is a strong signal on average. The held-out check shows it's the wrong signal for prompts about work in progress, which is where digests and meetings carry the context.

### Decision

The gate stays at 0.68 for every folder. Options B and C each trade relevant chunks for quiet at about the same rate, and a relevant chunk the hook drops is context Claude doesn't fetch. A real cut in noise needs something that reads the prompt better, not another cutoff.

### Consequences and check

- **The noise stays.** About 1.4 to 1.7 irrelevant chunks per prompt (80-prompt and held-out sets).
- **Search changes get a graded check.** `graph-memory/eval/judged_gate.py` runs before them. Its prompts and grades live beside the index, outside the repo, so a change that moves usefulness shows up with the numbers this ADR uses.
- **Revisit triggers.** A proposal that reads the prompt better, such as the conversation around a short reply, or `judged_gate.py` showing irrelevant chunks rising. A proposed cutoff has to be scored on prompts it wasn't tuned on.
- **The check.** On 2026-12-03, as in question 5.

## Changes

- 2026-11-03: proposed and decided.
