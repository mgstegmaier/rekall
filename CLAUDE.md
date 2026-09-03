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

Shipped: turn-key install, all three steps. Config lift (`3632e7f`), vault template + hooks +
skills (`60565d6`), and a full cold test of the `SETUP.md` paste on an empty folder: 43 meetings
→ 53 pages, hook answering, lint 0. Repo published public with squashed history; the 10-commit
original is on wiki page `rekall-git-history-pre-publish` and in `~/.config/rekall/backups/`.
Also fixed: distil child writing its own files (36 wasted Sonnet calls/hour); raw/ now distilled.

Open: `wiki-index.py` still can't run unattended in interactive ingests; pipeline writes a
Familiar-style `today.md` at the vault root, odd for a non-Familiar install; first hourly reindex
after a backfill distils every meeting (one Sonnet call each).

Next action: run `SETUP.md` on Jeff's Mac (VS Code extension; verify hooks fire and `claude` is
on PATH first).
