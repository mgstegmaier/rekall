# Rekall

Wiki machinery around an Obsidian vault: capture pipelines in, entity graph index, query layer
out. The vault owns the content; this repo owns the plumbing. Public at
https://github.com/mgstegmaier/rekall (fresh single-commit history since 2026-09-03).

- Every path and personal setting comes from `rekall.toml` (gitignored; copy
  `rekall.example.toml`) through `rekall_config.py`. `REKALL_CONFIG=/other.toml` points every
  script at another vault. Secrets: `.env` at the repo root (see `.env.example`) or Doppler.
- `graph-memory/` — the LIVE copy (hooks in `~/.claude/settings.json` and the hourly
  `com.heckatron.wiki-reindex` LaunchAgent point here). See `graph-memory/README.md`.
- `scripts/` — ingest pipeline, indexers, wiki lint/cleanup, wins mining.
- `cos/` — the chief of staff: `followups.py`, `prep.py`, `calendar-watch.py`, `status.py`, `gh.py`, `projects.py`,
  each with a `test_*.py`; config under `[cos]` in `rekall.toml`. Wiki page `pages/chief-of-staff.md` is the reference. `launchd/` — plist
  templates (`com.rekall.*`). `vault-template/` — what setup copies into a new vault.
- `SETUP.md` — the guided install (paste into Claude Code). `install.sh` — every step that writes
  outside the repo (hooks, skills, plists, allow rules); idempotent, `--uninstall` reverses it.
  `.claude/settings.json` — project ask rule so `bash install.sh` always prompts (loads only when
  Claude Code runs inside the rekall folder). `docs/obsidian-vault-cli.md` —
  vault CLI reference; read before any vault write. Wiki structure rules: vault `wiki/CLAUDE.md`.

## Current state (2026-09-07)

Shipped 2026-09-07 (`b718928` on main): the chief of staff in `cos/`
(ledger, meeting prep, calendar watch, Friday status, GitHub PRs as Shipped, rigor check, `repos:`
mapping), two skills (`prep`, `status`), two plists, `[cos]` config keys, pipeline steps 4 and 5,
`REKALL_NO_DIGEST` guard. Detail: wiki `pages/chief-of-staff.md` and the plan
`wiki/plans/2026-09-07-chief-of-staff-agent.md` (build log). Same commit carried the 09-04/09-07
`wiki/plans/` folder and "Mode: Plan" in `skills/wiki`.

Open: scheduled Graph calls paused by Mike (calendar watch unloaded, `prep_in_sweep = false`);
`com.rekall.status` Friday 15:00 has not had its first launchd run; `qval` and `doc-extraction`
have no `repos:` yet; Windows install and existing-vault
install still designed only (memory `existing-vault-install-design.md`); plugin packaging parked.

Next action: set `repos:` on the `qval` and `doc-extraction` pages, or resume scheduled Graph calls when ready (`prep_in_sweep`, calendar-watch plist). Jeff's install is done; a `git pull` on his clone brings in `cos/`.
