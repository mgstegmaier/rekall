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

Typed wiki graph shipped 2026-09-12/13 (`be95515`, `755e727`, `3f2ddd5`): relation frontmatter, `system`
and `pipeline` page types, typed edges, lint checks 11 to 13, a recall walk that skips `mentions` and
does not expand through person pages. Contextual retrieval measured 2026-09-13/14 (`5c0cffb`, `4d1c81d`,
next commit): title/description prefix kept, BGE-base and Haiku chunk contexts measured flat and not
kept, `[index] embedding_model` key, numpy scan, eval harness in `graph-memory/eval/`. Plans with every
number: `docs/plans/2026-09-12-typed-wiki-graph.md`, `docs/plans/2026-09-13-contextual-retrieval.md`.

Cost audit 2026-09-24 (wiki `pages/rekall.md` Updates has every number): schedules unchanged, per-run
work cut. `distil.py` child env strips `ANTHROPIC_API_KEY` (digests had failed on it); distil on Haiku
(`distil_model`), digest stays Sonnet. Recall hook: `MEANING_THRESHOLD = 0.68` (BGE-small only),
`GRAPH_BUDGET`, silent under `MEMORY_STARTER_CHILD`. Ingest: rules via `--append-system-prompt-file`,
Grep `index.md` never read whole, `--tools` + `--strict-mcp-config`, offline exits 0. `build_index.py`
reuses vectors by embed-text hash when the stored model matches; Sunday full is seconds, `--full` never
reuses. Live plists keep `com.heckatron.*` labels; `install.sh` would duplicate them, don't re-run it here.

Open: the eval's prompt set is contaminated by the sessions that built it (84 of 200 recent prompts
are about rekall itself) and the Haiku judge is uncalibrated; Windows cold test still unverified
(`docs/plans/2026-09-03-windows-install.md`); existing-vault install designed only; plugin packaging
parked; `loss-run-roots-project` ownerless by decision.

Next action: read the next real ingest batch's `total_cost_usd` against $1.25 to $3.79. Then a frozen
prompt set drawn from sessions outside the rekall repo plus a 50-prompt set Michael labels by hand, so
the judge can be calibrated (and the 0.68 recall cutoff checked) before any further retrieval change.
