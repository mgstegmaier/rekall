# Rekall

Wiki machinery around an Obsidian vault: capture pipelines in, entity graph index, query layer
out. The vault owns the content; this repo owns the plumbing. Public at
https://github.com/mgstegmaier/rekall (fresh single-commit history since 2026-09-03).

- Every path and personal setting comes from `rekall.toml` (gitignored; copy
  `rekall.example.toml`) through `rekall_config.py`. `REKALL_CONFIG=/other.toml` points every
  script at another vault. Secrets: `.env` at the repo root (see `.env.example`) or Doppler.
- `graph-memory/` — the LIVE copy (hooks in `~/.claude/settings.json` and the hourly
  `com.rekall.wiki-reindex` LaunchAgent point here). See `graph-memory/README.md`.
  `repo_sync.py` (the optional `com.rekall.repo-sync` job, `install.sh --with-repos`) keeps bare
  mirrors of the `[repos]` list at `<data>/repos/<name>.git`, state in `<state>/repo-sync-state.json`.
- `scripts/` — ingest pipeline, indexers, wiki lint/cleanup, wins mining.
- The chief of staff (ledger, prep, status, the plate) moved to its own private repo
  `~/github_repos/cos-desk` on 2026-09-07; wiki page `pages/chief-of-staff.md` is the reference. `launchd/` — plist
  templates (`com.rekall.*`). `vault-template/` — what setup copies into a new vault.
- `SETUP.md` — the guided install (paste into Claude Code). `install.sh` — every step that writes
  outside the repo (hooks, skills, plists, allow rules); idempotent, `--uninstall` reverses it.
  One install per machine and what a re-run refreshes: README "Upgrading". Maintainer rule: every
  skill, command, plist or task template install.sh writes goes through its substitution list,
  and skills and commands go through `place` (records in gitignored `.installed/`). A new
  placeholder goes in `subst_args`.
  `.claude/settings.json` — project ask rule so `bash install.sh` always prompts (loads only when
  Claude Code runs inside the rekall folder). `docs/obsidian-vault-cli.md` —
  vault CLI reference; read before any vault write. Wiki structure rules: vault `wiki/CLAUDE.md`.

## Current state (2026-11-03)

The 2026-11-01 review (`docs/plans/2026-11-01-rekall-review-v2/`, 41 findings) is fully built: its 16 batches and four
EGM designs merged as PRs #37 to #59. Index rebuilds are one transaction (ADR-002, check due 2026-11-15), the
recall-use log is v2 (each injection paired with its trigger; `--rebuild` regenerates it), and `install.sh` enforces one
install per machine and refreshes what it wrote on a re-run.

Also shipped: MCP server for Claude Desktop chat (`graph-memory/mcp_server.py`, `search_wiki` and `read_page`),
registered by `install.sh` step 6 (`7f55d1b`, `4e4d84f`, `0dea1ca`). README section "Use your wiki from
Claude Desktop chat" merged in PR #7. Cost audit 2026-09-24 numbers live on wiki `pages/rekall.md`.
Repo mirrors phase 1 merged 2026-11-03 (PR #63, ADR-004): five repos mirrored under `<data>/repos/`, synced by
`com.rekall.repo-sync`; phase 2 (`repos.db`, `search_repo_docs`) waits for ADR-002's 2026-11-15 check.
This machine runs the released install (`bash install.sh --with-graph --with-repos`, `com.rekall.*` labels) since 2026-11-01; the old `com.heckatron.*` plists sit in `~/.config/rekall/backup-plists/`. Re-running `install.sh` is safe from Terminal.app. Don't run it from a Claude session on this Mac: SentinelOne reads
the LaunchAgent writes and `launchctl bootstrap` as malware persistence, kills the session and quarantines its whole
process chain (2026-10-21 and 2026-11-04; README "Upgrading").
Changes go through a PR; never merge into `main` locally.

Open: eval prompt set contaminated and Haiku judge uncalibrated (recheck 0.68 with
`~/.config/rekall/eval/recall-threshold-calibrate.py`); Windows cold test unverified; existing-vault
install designed only; plugin packaging parked.

Next action: none on cost. The 28 ingest batches from 2026-10-05 to 2026-11-01 cost $0.22 to $0.63 each, plus one $1.42 backfill; check a new batch against that range.
