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
- The chief of staff (ledger, prep, status, the plate) moved to its own private repo
  `~/github_repos/cos-desk` on 2026-09-07; wiki page `pages/chief-of-staff.md` is the reference. `launchd/` — plist
  templates (`com.rekall.*`). `vault-template/` — what setup copies into a new vault.
- `SETUP.md` — the guided install (paste into Claude Code). `install.sh` — every step that writes
  outside the repo (hooks, skills, plists, allow rules); idempotent, `--uninstall` reverses it.
  `.claude/settings.json` — project ask rule so `bash install.sh` always prompts (loads only when
  Claude Code runs inside the rekall folder). `docs/obsidian-vault-cli.md` —
  vault CLI reference; read before any vault write. Wiki structure rules: vault `wiki/CLAUDE.md`.

## Current state (2026-10-07)

Shipped: MCP server for Claude Desktop chat (`graph-memory/mcp_server.py`, `search_wiki` and `read_page`),
registered by `install.sh` step 6 (`7f55d1b`, `4e4d84f`, `0dea1ca`). README section "Use your wiki from
Claude Desktop chat" merged in PR #7. Cost audit 2026-09-24 numbers live on wiki `pages/rekall.md`.
Live plists keep `com.heckatron.*` labels; `install.sh` would duplicate them, so don't re-run it here.
Changes go through a PR; never merge into `main` locally.

Open: eval prompt set contaminated and Haiku judge uncalibrated (recheck 0.68 with
`~/.config/rekall/eval/recall-threshold-calibrate.py`); Windows cold test unverified; existing-vault
install designed only; plugin packaging parked.

Next action: read the next real ingest batch's `total_cost_usd` against $1.25 to $3.79.
