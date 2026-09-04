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

Shipped today: `install.sh` (PR #1); `type` as the single taxonomy field with flat `wiki/pages/` and
one Base per type (PRs #2, #3); three-stage page lifecycle `status: active|retired|archive`, where
`scripts/wiki-cleanup.py` moves archive-marked files to `wiki/archive/` and never deletes (commit
`76be8be`; self-check `scripts/test_wiki_cleanup.py`). Detail: wiki `pages/rekall.md`.

Open: `wiki-index.py` can't run unattended in interactive ingests; pipeline writes a Familiar-style
`today.md` at the vault root; first reindex after a backfill distils every meeting; Windows install
planned (`docs/plans/2026-09-03-windows-install.md`). Designed, not built: existing-vault install
(layered `install.sh [wiki|recall]`, minimal contract, ownership stamp) — project memory
`existing-vault-install-design.md`. Parked: plugin packaging, pros and cons first.

Next action: finish Jeff's install (`git pull`, `bash install.sh`, confirm recall fires).
