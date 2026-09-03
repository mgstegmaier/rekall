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
SESSIONS = VAULT / "memory" / "sessions"
DATA = Path(_cfg["data"]["path"]).expanduser()
# pipeline state, lint state, locks, logs. Per install, so two installs on one machine stay apart.
STATE_DIR = Path(_cfg["data"].get("state", "~/.config/rekall")).expanduser()
MONDAY_BOARD = int(_cfg.get("monday", {}).get("board", 0))
MONDAY_GROUP = _cfg.get("monday", {}).get("group", "Auto-Capture")

if __name__ == "__main__":
    names = sys.argv[1:] or ["USER_NAME", "TIMEZONE", "VAULT", "WIKI", "SESSIONS", "DATA", "STATE_DIR", "MONDAY_BOARD", "MONDAY_GROUP"]
    for n in names:
        print(globals()[n] if len(names) == 1 else f"{n}={globals()[n]}")
