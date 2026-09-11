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

## Current state (2026-09-10)

Shipped 2026-09-07 (`b718928` on main): the chief of staff, the `wiki/plans/` folder and "Mode: Plan" in
`skills/wiki`. Later the same night the chief of staff moved out to `~/github_repos/cos-desk` (private,
`mgstegmaier/cos-desk`): `cos/`, the `prep`/`status` skills, the two plists, the `[cos]` config keys, and
pipeline steps 4 and 5 are gone from this repo. The ledger renders on its own 15-minute timer there
(`com.cos.followups`). Detail: wiki `pages/chief-of-staff.md`.

Windows support landed 2026-09-10 in the same commit as the `cos/` removal: `acquire_lock` (fcntl or
msvcrt) in the pipeline, log-only notifications on `nt`, `PYTHON`/`sys.executable` instead of a literal
`python3`, `__VENV_PY__` in `hooks.json`, `windows/*.xml` Task Scheduler templates, and a Windows branch
in `install.sh` (Register-ScheduledTask, probed `sed -i`, tzdata). Both branches were checked with
stubbed `launchctl`/`cygpath`/`powershell.exe`; the Mac hook command is byte-identical, so existing
installs see no change. Plan: `docs/plans/2026-09-03-windows-install.md`. The onboarding runbook for Upland machines is a
private wiki page (`rekall-windows-onboarding`); this repo stays free of employer names and ids.

Open: nothing has run on a real Windows machine, so Task Scheduler accepting the XML is unverified.
Existing-vault install still designed only (memory `existing-vault-install-design.md`); plugin packaging
parked.

Next action: cold test on Windows, 2026-09-11, with a second install on 2026-09-16.
