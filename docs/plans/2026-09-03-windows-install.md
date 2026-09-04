# Windows install, alongside the Mac install

**Status:** planned 2026-09-03, nothing built. The Mac install is done and cold-tested (see `SETUP.md`).

## Goal

The same one-paste install on Windows. Same `SETUP.md`, same setup message, Claude branches on the
OS inside the steps. No second document to keep in sync.

## What already works on Windows

Claude Code on Windows requires Git for Windows, so Git Bash is present on every machine that can
run the paste. That carries most of the repo across unchanged:

- The three bash launchers (`reindex.sh`, `fetch_model.sh`, `run-fathom-pipeline.sh`) run under
  Git Bash. `curl` ships with Windows 10 and later.
- `rekall_config.py`, `paths.py`, and every path built from `Path.home()` work as-is.
  `~/.config/rekall` is an ordinary folder on Windows.
- The vendored index code already branches: `session_end.py` uses `DETACHED_PROCESS` on `nt`,
  and `distil.py` wraps a `claude.cmd` shim in `cmd /c`.
- `hooks.json` entries run through Claude Code's hook runner, which uses Git Bash on Windows.
- The Obsidian CLI and the wiki skill are platform-neutral.

## What has to change

| Piece | Mac today | Windows | Change |
|-------|-----------|---------|--------|
| Run lock in `fathom-pipeline.py` | `fcntl.flock` | no `fcntl` module | try `fcntl`, fall back to `msvcrt.locking` on the same file handle. Same semantics: non-blocking exclusive lock, released on process exit |
| Notifications in `fathom-pipeline.py` and `wiki-lint.py` | `osascript` | no `osascript` | on `nt`, log only. The scheduled task's redirected output is the record. A toast needs a module that isn't installed by default |
| venv interpreter path in `reindex.sh` and `hooks.json` | `.venv/bin/python` | `.venv/Scripts/python.exe` | `reindex.sh`: pick whichever exists. `hooks.json`: a second placeholder, `__VENV_PY__`, that setup fills with the right relative path |
| `python3` as a command name in `run-fathom-pipeline.sh`, `fetch_model.sh`, and two `subprocess.run` calls in the pipeline | `python3` | python.org installs `python` and `py`, not `python3` | shell: `PYTHON=${PYTHON:-$(command -v python3 \|\| command -v python)}`. Pipeline: call `sys.executable` for its own helpers instead of `"python3"` |
| Time zones | system tz database | Windows has none; `zoneinfo` raises | `pip install tzdata` into the venv, and run the pipeline with the venv interpreter so it sees it. Setup does both |
| Schedules | three launchd plists in `launchd/` | Task Scheduler | three task definitions in `windows/`, created with `schtasks /Create /XML` from templates, same placeholders. Hourly reindex: `/SC HOURLY`. Pipeline: daily trigger at 07:15 repeating hourly for 12 hours. Lint: daily 21:30. Each task runs `bash.exe` from Git for Windows with the script path |
| Corporate CA fix in `SETUP.md` | `security find-certificate` | Windows cert store | probably unnecessary: Python on Windows loads the system store when `ssl.create_default_context()` is used without a bundle, which is the pipeline's default path. Verify on a corporate laptop; if it fails, `certutil -store Root` exports the proxy CA and the same bundle recipe applies |
| `chmod 600 .env` | works | no-op | skip on `nt`; `.env` sits in the user's profile, which is already user-only |
| `.gitkeep`-style empty folders | fine | fine | nothing |
| Step 1 machine check in the setup message | "macOS" | Windows 10 or later | the check names both OSes and tells Claude which branch to take for schedules |

Nothing in the wiki, the index format, the digest, or the recall hook changes.

## SETUP.md shape after the change

One setup message. Steps 1, 5, 8, and 10 gain an "on Windows" clause; the rest are identical.
The corporate CA note gains a Windows paragraph. The bootstrap paste is unchanged.

## Order of work, each with its check

1. Code: lock fallback, log-only notifications, `sys.executable`, `PYTHON` detection, venv path
   detection in `reindex.sh`, `tzdata` in the venv requirements. Check: Mac install unchanged
   (pipeline dry-run, reindex counts).
2. `windows/` task templates and the `__VENV_PY__` placeholder in `hooks.json`. Check: `schtasks`
   accepts each XML on a Windows box.
3. `SETUP.md` OS clauses. Check: read-through on both branches.
4. Cold test on the Windows desktop (Mike's secondary machine): empty folder, scratch config via
   `REKALL_CONFIG`, own Fathom key, same numbers expected as the Mac test (meetings in, pages out,
   hook answering, lint 0). Fix what breaks.

## Out of scope

Doppler on Windows (the `.env` path is the Windows path). WSL (Git Bash is enough and is what
Claude Code already needs). PowerShell rewrites of the bash launchers.
