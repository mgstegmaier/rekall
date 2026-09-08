"""Rekall settings, read from rekall.toml at the repo root.

Copy rekall.example.toml to rekall.toml and edit it. Secrets never go here; they
live in .env (see .env.example). Every script imports its paths from this module,
and shell scripts ask it for one value: `python3 rekall_config.py VAULT`.
Set REKALL_CONFIG=/path/to/other.toml to run everything against a different vault.
"""

import os
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
# REKALL_CONFIG points at another toml for tests and cold installs; default is the repo's own.
_FILE = Path(os.environ.get("REKALL_CONFIG", ROOT / "rekall.toml"))
if not _FILE.exists():
    sys.exit(f"missing {_FILE}: copy rekall.example.toml to rekall.toml and edit it")
_cfg = tomllib.loads(_FILE.read_text(encoding="utf-8"))

USER_NAME = _cfg["user"]["name"]
TIMEZONE = _cfg["user"]["timezone"]
VAULT = Path(_cfg["vault"]["path"]).expanduser()
WIKI = VAULT / "wiki"
SESSIONS = WIKI / "sessions"  # digests moved into the wiki 2026-09-04
ARCHIVE = WIKI / _cfg.get("wiki", {}).get("archive", "archive")  # lifecycle job's destination
DATA = Path(_cfg["data"]["path"]).expanduser()
# pipeline state, lint state, locks, logs. Per install, so two installs on one machine stay apart.
STATE_DIR = Path(_cfg["data"].get("state", "~/.config/rekall")).expanduser()
MONDAY_BOARD = int(_cfg.get("monday", {}).get("board", 0))
MONDAY_GROUP = _cfg.get("monday", {}).get("group", "Auto-Capture")
# Chief-of-staff: whose meeting to-dos the follow-ups ledger tracks. Names as they appear in notes.
COS_ME = _cfg.get("cos", {}).get("me", [USER_NAME])
COS_TRACKED = _cfg.get("cos", {}).get("tracked", {})  # {"Display Name": ["alias", ...]}
COS_GITHUB_ORGS = _cfg.get("cos", {}).get("github_orgs", [])  # PRs counted only from these owners; [] = all
# Off by default: prep needs the Microsoft Graph token, and Mike paused every scheduled Graph call on 2026-09-07.
COS_PREP_IN_SWEEP = bool(_cfg.get("cos", {}).get("prep_in_sweep", False))
# Optional script that prints a Monday board snapshot JSON; its on_hold items feed the ledger's waiting_on.
_snap = _cfg.get("cos", {}).get("monday_snapshot", "")
COS_MONDAY_SNAPSHOT = Path(_snap).expanduser() if _snap else None
# Your manager, as named in 1:1 note filenames; picks the "You owe" rows for cos/status.py.
COS_STATUS_AUDIENCE = _cfg.get("cos", {}).get("status_audience", "")

if __name__ == "__main__":
    names = sys.argv[1:] or ["USER_NAME", "TIMEZONE", "VAULT", "WIKI", "SESSIONS", "ARCHIVE", "DATA", "STATE_DIR", "MONDAY_BOARD", "MONDAY_GROUP", "COS_ME", "COS_TRACKED", "COS_MONDAY_SNAPSHOT", "COS_STATUS_AUDIENCE"]
    for n in names:
        print(globals()[n] if len(names) == 1 else f"{n}={globals()[n]}")
