"""Rekall settings, read from rekall.toml at the repo root.

Copy rekall.example.toml to rekall.toml and edit it. Secrets never go here; get_secret()
below reads them from the environment, the OS keyring, or a legacy .env. Every script imports its paths from this module,
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
EMBEDDING_MODEL = _cfg.get("index", {}).get("embedding_model", "BAAI/bge-small-en-v1.5")
# Optional Microsoft Graph ingest (scripts/graph-ingest.py); off unless enabled = true.
GRAPH = _cfg.get("graph", {})
# Research sweep (fathom-pipeline links wiki/pages/research/ memos onto the pages they name); on unless enabled = false.
RESEARCH = _cfg.get("research", {})
# Optional command the launchers put in front of each job, e.g. "doppler run --project p --config c --".
RUN_PREFIX = _cfg.get("secrets", {}).get("run_prefix", "")

ENV_FILE = ROOT / ".env"  # legacy store, checked last so existing installs keep working
KEYRING_SERVICE = "rekall"


def find_secret(name):
    """Value for name from the environment, then the OS keyring, then .env; None when all are empty."""
    if os.environ.get(name):
        return os.environ[name]
    try:  # a missing package or a broken backend falls through to .env
        import keyring
        value = keyring.get_password(KEYRING_SERVICE, name)
        if value:
            return value
    except Exception:
        pass
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            k, sep, v = line.partition("=")
            if sep and k.strip() == name and v.strip():
                return v.strip().strip("\"'")
    return None


def get_secret(name):
    value = find_secret(name)
    if value is None:
        raise KeyError(f"{name} not in environment, keyring (service {KEYRING_SERVICE!r}), or {ENV_FILE}")
    return value


def set_secret(name, value):
    import keyring
    keyring.set_password(KEYRING_SERVICE, name, value)


if __name__ == "__main__":
    names = sys.argv[1:] or ["USER_NAME", "TIMEZONE", "VAULT", "WIKI", "SESSIONS", "ARCHIVE", "DATA", "STATE_DIR", "MONDAY_BOARD", "MONDAY_GROUP", "EMBEDDING_MODEL"]
    for n in names:
        print(globals()[n] if len(names) == 1 else f"{n}={globals()[n]}")
