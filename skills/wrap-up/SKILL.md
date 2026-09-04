---
name: wrap-up
description: Session wrap-up — persist what changed this session into the right places so the next session starts oriented. Use when the user says "wrap up", "wrap up the session", "let's wrap up", or signals end of a work session. Updates the active project's CLAUDE.md "Current state" block and auto-memory by default, updates the wiki project page only if the session changed what it describes, and reconciles contradictions or dangling references the session introduced.
allowed-tools: Read, Grep, Glob, Edit, Write, Bash
---

# Session wrap-up

Persist what changed this session into a small, fixed set of homes, then reconcile. Goal: the next
session lands oriented, with no stale or contradictory notes. The failure this prevents is
**scattered notes and a missed location**, so sweep every home, every time.

Best run at a natural stopping point while context is still sharp, not on a near-full window.

The session-end digest (the `SessionEnd` hook) captures every session automatically into
`memory/sessions/` in the vault. Wrap-up is the deliberate close-out on top of it: it decides what
from this session belongs on a project page, not only in a digest.

## 0. Scope the session

- Identify which project we worked in. If more than one materially changed and it's ambiguous, ask
  which to wrap up. Default: the working directory.
- Skim the conversation for what MATERIALLY changed: decisions made, durable facts learned, fixes,
  files created/deleted/renamed, items opened or closed, preferences the user expressed.
- If nothing durable changed, say so and stop. Don't manufacture updates.

## 1. Default targets (most sessions)

**a. The project CLAUDE.md "Current state" block**, the live-state home. It rides CLAUDE.md because
CLAUDE.md auto-loads every session; a separate status file only works if someone remembers to read it.

- Format: a `## Current state (YYYY-MM-DD)` section: what shipped (1–2 lines), what's open,
  and ONE next action. Budget: about 12 lines, hard.
- REPLACE the block, never append below it. If the outgoing block holds anything durable, move that
  to memory or the wiki first, then overwrite.
- Detail lives in its record (a commit, a doc, a wiki page). The block POINTS at records, it never
  re-narrates them.
- No block yet? Offer to add one. Skip it for one-off or trivial sessions.

**b. Auto-memory** (`~/.claude/projects/<project-key>/memory/` plus its `MEMORY.md` index):

- Add or update memory files for durable cross-session facts, lessons, and preferences. One fact per
  file, with frontmatter (`name`, `description`, `metadata: type:` = user|feedback|project|reference);
  `feedback` and `project` entries get **Why:** and **How to apply:** lines.
- UPDATE an existing file that already covers the fact rather than duplicating; delete memories
  proven wrong. New memory means a one-line pointer in `MEMORY.md`.
- Don't save what the repo, git history, CLAUDE.md, or the wiki already records.

## 2. Conditional target: the wiki project page (touch ONLY if the session changed what it describes)

The page lives at `wiki/pages/<project>.md` (`type: project`) in the vault named by `rekall.toml`. Update it when the
session materially changed what the page describes: a decision made, a phase shipped, architecture
changed, a project started or renamed. Update State and Next steps with citations, and append an
entry to `wiki/log.md` (append-only, at the end). Structure rules are in the vault's `wiki/CLAUDE.md`.

- **Promote from the session digests.** Read the newest 2–3 files in `memory/sessions/` (this
  session's own digest lands only after close). Promote any Decisions or durable Facts about this
  project that never made it onto the page, citing the digest file as the source.
- **Sweep `[open]` loops.** From those same digests, mark the loops this session closed and carry
  the still-live ones into the page's Next steps. Loops live on the project page, not scattered
  across digest files.
- **Project CLAUDE.md body** (outside the Current state block): update only if conventions or
  commands changed.

Do not update these by reflex. If unchanged, leave them.

## 3. Reconcile (the step that's usually missed)

- **Sweep the session scratchpad**: any durable artifact written there (a script, a report, anything
  a doc or memory now references) gets COPIED into the workspace before the session ends. The
  scratchpad dies with the session. Remove dead temp files.
- Grep the project for references to any file created, deleted, or renamed this session; fix
  dangling references.
- Check the orientation docs (CLAUDE.md, README, project memory) against what's now true. Stale
  claims get fixed or repointed to the live source.
- Single source of truth: each fact lives in ONE canonical home; other homes point at it.

## 4. Report

Short:

- What changed this session (1–3 lines).
- Exactly what you updated and WHERE, file by file.
- Anything you were UNSURE whether to persist: list it and let the user decide. Don't silently drop
  a judgment call, and don't silently save one either.
- ONE next action.

## Principles

- **Fewer note locations beats more.** Don't create new docs or structure without a concrete need;
  prefer the existing canonical home.
- **Don't let a doc rot:** if a section is now wrong, fix it.
- **Verify against the actual files** before recording state; don't trust the conversation's
  summary of itself.
