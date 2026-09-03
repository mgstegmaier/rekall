# Cutover: Familiar to Rekall

The wiki machinery was copied out of the Familiar repo on 2026-09-01 with all internal paths rewritten (`personal_projects/familiar` to `personal_projects/rekall`, `.config/familiar` to `.config/rekall`).

**Status 2026-09-01: steps 1 through 5 are DONE and verified.** Venv rebuilt; state copied to `~/.config/rekall/` (graph-memory data needed no move, it lives in `~/obsidian-vault/graph-memory/`, repo-independent); all three launchd jobs reloaded from the rewritten plists and smoke-tested (lint ran, recall hook returned hits, a kicked Fathom run reported "0 new" against the copied state); `~/.claude/skills/wiki` is now a symlink into this repo; pointers updated in `~/.claude/settings.json` (both graph-memory hooks, found during cutover and missing from the original list below), `~/.claude/commands/fathom-sync.md`, `~/.claude/rules/familiar-obsidian-vault.md` plus its source `familiar/identity/obsidian-vault.md` (edit left uncommitted in Familiar), and the vault's `wiki/CLAUDE.md`. Only step 6 remains.

1. Rebuild the graph-memory venv here: `cd graph-memory && python3 -m venv .venv && .venv/bin/pip install -r requirements` (check `README.md` for the actual dependency list; the old venv at `familiar/graph-memory/.venv` was not copied).
2. Move runtime state so nothing re-ingests or re-notifies: copy `~/.config/familiar/fathom-pipeline-state.json`, `wiki-lint-state.json`, `ca-bundle.pem`, and `logs/` to `~/.config/rekall/`. The fathom state file is the important one: losing it makes the pipeline treat every past meeting as new.
3. Swap the launchd jobs: `launchctl unload` the three installed plists in `~/Library/LaunchAgents/` (`com.heckatron.wiki-lint`, `com.heckatron.fathom-pipeline`, `com.heckatron.wiki-reindex`), copy the rewritten plists from `scripts/` and `graph-memory/` over them, `launchctl load` the new ones, and confirm with `launchctl list | grep heckatron`.
4. Repoint the live skill: replace `~/.claude/skills/wiki/` with the copy in `skills/wiki/` (or symlink it here).
5. Update the pointers that still name Familiar: the vault's `wiki/CLAUDE.md` (index and cleanup script paths), `~/.claude/rules/familiar-obsidian-vault.md` (the cleanup-job exception names `familiar/scripts/wiki-cleanup.py`), and Familiar's own `docs/obsidian-vault-cli.md` pointer in the rules.
6. Only after a full day of green launchd runs: delete the wiki scripts, plists, graph-memory/, and the two wiki plan docs from the Familiar repo, and note the move in Familiar's docs.

Not copied, on purpose: `flatten-wiki.py` and `okf-restructure.py` (completed one-shot migrations; they stay in Familiar's history), the graph-memory venv and generated data (`rag.db`, `__pycache__`, digest outputs).
