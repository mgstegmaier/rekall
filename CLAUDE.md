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
- `SETUP.md` — the guided install (paste into Claude Code). `docs/obsidian-vault-cli.md` —
  vault CLI reference; read before any vault write. Wiki structure rules: vault `wiki/CLAUDE.md`.

## Current state (2026-09-03)

Shipped: the turn-key Mac install, cold-tested end to end from the one-paste bootstrap in
README/`SETUP.md` (43 meetings → 53 pages, hook answering, lint 0). Repo public with squashed
history (original on wiki page `rekall-git-history-pre-publish` + `~/.config/rekall/backups/`).
Distil fix (child was writing files; 36 wasted calls/hour) and raw/ distillation. Windows install
planned, not started: `docs/plans/2026-09-03-windows-install.md`. Detail: wiki `projects/rekall.md`.

Open: `wiki-index.py` can't run unattended in interactive ingests; pipeline writes a Familiar-style
`today.md` at the vault root; first reindex after a backfill distils every meeting (one call each);
`graph-memory/README.md` ops table still shows Mike's literal paths.

Next action: run the bootstrap paste on Jeff's Mac (VS Code extension; first verify hooks fire
there and `claude` is on PATH).
