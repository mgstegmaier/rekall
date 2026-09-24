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

## Current state (2026-09-24)

Shipped: typed wiki graph (2026-09-12/13) and contextual retrieval measured flat (2026-09-14), plans in
`docs/plans/`. Cost audit 2026-09-24 (`7190513`, `eda6799`; every number on wiki `pages/rekall.md`):
digest auth fix, recall cutoff `MEANING_THRESHOLD = 0.68` (BGE-small only), ingest rules as cached system
prompt with no Bash (path guard covers every tool), vector reuse in `build_index.py`, distil on Haiku.
Live plists keep `com.heckatron.*` labels; `install.sh` would duplicate them, so don't re-run it here.

Open: eval prompt set contaminated and Haiku judge uncalibrated (recheck 0.68 with
`~/.config/rekall/eval/recall-threshold-calibrate.py`); Windows cold test unverified; existing-vault
install designed only; plugin packaging parked.

Next action: read the next real ingest batch's `total_cost_usd` against $1.25 to $3.79.
