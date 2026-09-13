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

## Current state (2026-09-13)

Typed wiki graph shipped 2026-09-12 and 2026-09-13 (`be95515`, `755e727`, `3f2ddd5` on main): relation
frontmatter (`owner`, `people`, `maintainers`, `depends_on`, `part_of`, `about`, pipeline flow fields,
`attendees`, `aliases`), `system` and `pipeline` page types, typed edges in `build_graph.py`, lint checks
11 to 13, and a recall walk that skips `mentions` and does not expand through person pages. Plan, every
measurement, and what was tried and reverted: `docs/plans/2026-09-12-typed-wiki-graph.md`. Eval harness:
`graph-memory/eval/`. Backfill applier: `scripts/wiki-apply-props.py`.

Open: Windows cold test still unverified (`docs/plans/2026-09-03-windows-install.md`); existing-vault
install designed only (memory `existing-vault-install-design.md`); plugin packaging parked; one active
project page without an owner by decision (`loss-run-roots-project`).

Next action: `/prep` and `/wiki` query should read the typed graph (`owns`, `maintains`, `about`), the
consumers the graph was built for; the hook already does.
