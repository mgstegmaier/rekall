---
adr: 3
title: Read tracked GitHub repos from full bare mirrors through origin/<branch>, and give repo docs their own index instead of the wiki's
date: 2026-11-03
status: DECIDED
decider: mgstegmaier
recorded_by: Claude Code, in the rekall repo-mirrors phase 1 night-shift session
ticket:
validation_by: 2026-11-15
decided: 2026-11-03, EGM design review of "Searchable repo mirrors for rekall"
reversible: yes
---

# ADR-003: Read tracked GitHub repos from full bare mirrors through origin/<branch>, and give repo docs their own index instead of the wiki's

## Summary

**Where it stands.** Decided. Phase 1 (the mirrors, the sync job, the hook's stale line and the routing skill) is built in the phase 1 PR. The separate index (`repos.db` and `search_repo_docs`) is phase 2, which waits for ADR-002's check on 2026-11-15.

### The problem

Claude sees the user's repos only through local clones, which sit on feature branches and fall behind `main`. On 2026-09-07 local `main` was more than 300 commits behind in two of the tracked repos, so Claude read old code and missed teammates' merged PRs. One clone also held 1,324 markdown files inside `.claude/worktrees/` copies, so a search of the folder returned the same docs many times over. The decisions behind the code (ADRs, OKF pages, PR descriptions) can only be found by someone who knows which file to open.

### The recommendation

Rekall keeps a full bare mirror of each repo listed under `[repos]` in `rekall.toml`, fetched at 07:00 and 13:00 by its own LaunchAgent. Every GitHub branch lands under `origin/*`, HEAD points at `origin/<branch>`, and there are no local branches to fall behind. Claude reads with `git show`, `git grep` and `git log` against `origin/main`. Repo docs, PR digests and generated dbt pages go into a second index, `repos.db`, reached on purpose through `search_repo_docs` and `search.py --repos`; the recall hook stays wiki-only. The cost is disk space for full history (expected at 4 to 15 MB per repo) and one more scheduled job.

### Other options

| Option | Trade-off |
|---|---|
| A. Index repo docs into `rag.db` with `--extra` | No new database or tool, and the hook surfaces repo docs unasked; but repo text competes with wiki pages for the hook's top five, and `--extra` file keys break the recall-use log. |
| B. A working-tree checkout of `main` | Plain paths any editor can open; but Claude could edit it, and the next reset wipes the edit silently. |
| C. Fetch the existing clones in place | Smallest change; but a background fetch contends with the user's own git commands, works only for repos already cloned, and gives Claude Desktop nothing. |
| D. Partial or shallow mirrors | Smaller on disk; but `git grep` on a partial clone downloads files one request at a time and fails offline, and a shallow clone can't answer "what changed". |
| H. A repo slot in the recall hook | Repo docs would surface without a search; but the cosine floor was tuned on wiki text, and the eval set is contaminated, so nothing could show the slot helps. |
| I. GitHub's MCP server or `gh api` search | Off the shelf, with no local copies; but keyword-only search, rate limits and SSO rules on every read, and nothing offline. |

### Decision needed

- None. Decided by mgstegmaier in the 2026-11-03 design review.

## Detail

### The decision check

1. Waiting keeps Claude reading stale clones, the problem above. It was on the table and rejected.
2. The facts are the ones measured on 2026-09-07 and 2026-11-03 in the design.
3. Each option is priced above. The hidden cost of the chosen one is a second index to keep healthy, which is why phase 2 waits for ADR-002's check.
4. The user decided it in the design review.
5. The check: on 2026-11-15, ADR-002's check passes (digest rebuilds fail less than once a week) before phase 2 merges; and once phase 1 runs live, every mirror's `git rev-parse HEAD` equals `git rev-parse origin/main`, and `graph-memory/eval/gate.py` prints the same output before and after.

### Context

The design is "Searchable repo mirrors for rekall" (2026-11-03), filed in the vault's `wiki/plans/2026-11-03-repo-search-targets/`. It ships in four phases: mirrors and the sync job, the search index, PR digests, and a private dbt page generator run through a generic `generators` setting.

### Decision

Full bare mirrors read through `origin/<branch>`, refreshed by a job of their own, because they give current `main` with history, offline grep and no working copy to edit by accident. A separate index, because wiki recall is rekall's core job and repo text would crowd it.

### Consequences and check

Rekall now owns `<data>/repos/`, the `com.rekall.repo-sync` job and its state file. The tracked repo names live only in the gitignored `rekall.toml`, the data folder and the state file, so the public repo carries none. Mirrors of repos removed from config stay on disk until deleted by hand. The dated check is under question 5.

## Changes

- 2026-11-03: decided in the design review; phase 1 built.
