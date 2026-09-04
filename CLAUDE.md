# Rekall

Wiki machinery around an Obsidian vault: capture pipelines in, entity graph index, query layer
out. The vault owns the content; this repo owns the plumbing. Public at
https://github.com/mgstegmaier/rekall (fresh single-commit history since 2026-09-03).

- Every path and personal setting comes from `rekall.toml` (gitignored; copy
  `rekall.example.toml`) through `rekall_config.py`. `REKALL_CONFIG=/other.toml` points every
  script at another vault. Secrets: `.env` at the repo root (see `.env.example`) or Doppler.
- `graph-memory/` — the LIVE copy (hooks in `~/.claude/settings.json` and the hourly
  `com.heckatron.wiki-reindex` LaunchAgent point here). See `graph-memory/README.md`.
- `scripts/` — ingest pipeline, indexers, wiki lint/cleanup, wins mining. `launchd/` — plist
  templates (`com.rekall.*`). `vault-template/` — what setup copies into a new vault.
- `SETUP.md` — the guided install (paste into Claude Code). `install.sh` — every step that writes
  outside the repo (hooks, skills, plists, allow rules); idempotent, `--uninstall` reverses it.
  `.claude/settings.json` — project ask rule so `bash install.sh` always prompts (loads only when
  Claude Code runs inside the rekall folder). `docs/obsidian-vault-cli.md` —
  vault CLI reference; read before any vault write. Wiki structure rules: vault `wiki/CLAUDE.md`.

## Current state (2026-09-04)

Shipped: turn-key Mac install (`install.sh`, one approval; cold-tested), repo public with squashed
history, raw/ distillation. 2026-09-04 evening: wiki schema change. `type` is the single taxonomy
field (`wiki-type` retired) and the five type folders collapsed into flat `wiki/pages/` with one Base
per type at the wiki root; the graph builder reads type from frontmatter (PRs #2, #3). Detail: wiki
`pages/rekall.md`; migration `scripts/wiki-retype.py`. Later the same day: three-stage page lifecycle.
`status: active|retired|archive` stamped on every page and meeting note; `scripts/wiki-cleanup.py`
MOVES `archive`-marked files to `wiki/archive/` (`[wiki].archive` in rekall.toml), never deletes,
rewrites no links; lint check 10 enforces the field; the wiki-lint plist runs the job after the report.
Self-check: `scripts/test_wiki_cleanup.py`.

Open: `wiki-index.py` can't run unattended in interactive ingests; pipeline writes a Familiar-style
`today.md` at the vault root; first reindex after a backfill distils every meeting; `graph-memory/
README.md` shows Mike's literal paths; Windows install planned (`docs/plans/2026-09-03-windows-install.md`).

Next action: run the bootstrap paste on Jeff's Mac (verify hooks fire and `claude` is on PATH).
Parked: package Rekall as a plugin; Mike wants pros and cons first. Existing-vault install (layered
`install.sh [wiki|recall]`, minimal contract, ownership stamp, synthetic fixture vaults) is designed
but not built; design notes in project memory `existing-vault-install-design.md`.
