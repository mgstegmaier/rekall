"""Rekall settings, read from rekall.toml at the repo root.

Copy rekall.example.toml to rekall.toml and edit it. Secrets never go here; get_secret()
below reads them from the environment, the OS keyring, or a legacy .env. Every script imports its paths from this module,
and shell scripts ask it for one value: `python3 rekall_config.py VAULT`.
Set REKALL_CONFIG=/path/to/other.toml to run everything against a different vault.
"""

import json
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


_KEYRING_WARNED = False


def _warn_no_keyring(exc):
    """Say once per process that the OS vault was skipped. A silent fall-through here cost three
    hours on 2026-10-26: the runner's venv had no keyring module, so every scheduled job read a
    .env with no CLAUDE_CODE_OAUTH_TOKEN in it and ran as though nobody had ever signed in."""
    global _KEYRING_WARNED
    if _KEYRING_WARNED:
        return
    _KEYRING_WARNED = True
    print(f"rekall: the OS vault was skipped ({type(exc).__name__}: {exc}), so secrets come from "
          f"{ENV_FILE} only. Fix: {sys.executable} -m pip install keyring", file=sys.stderr)


def find_secret(name):
    """Value for name from the environment, then the OS keyring, then .env; None when all are empty."""
    if os.environ.get(name):
        return os.environ[name]
    try:  # a missing package or a broken backend falls through to .env
        import keyring
        value = keyring.get_password(KEYRING_SERVICE, name)
        if value:
            return value
    except Exception as exc:
        _warn_no_keyring(exc)
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


def claude_env(env):
    """env with the stored Claude token added, for a claude -p child. The settings page saves it
    (claude setup-token), so scheduled jobs run without an interactive login. Without one the
    child falls back to the CLI's own login, as before."""
    token = find_secret("CLAUDE_CODE_OAUTH_TOKEN")
    if token:
        env["CLAUDE_CODE_OAUTH_TOKEN"] = token
    return env


# Claude sign-in health. Plain files, because the recall hook checks them on every prompt and must
# not touch the keychain that often.
AUTH_FAILED = STATE_DIR / "claude-auth-failed"     # a scheduled claude -p call was refused; cleared on success
TOKEN_INFO = STATE_DIR / "claude-token.json"       # when the settings page last saved a token
REAUTH_PROMPTED = STATE_DIR / "claude-reauth-prompted"
TOKEN_WARN_DAYS = 330  # ponytail: the CLI calls the token long-lived; warn a month before a year
AUTH_ERRORS = ("not logged in", "/login", "invalid api key", "oauth token", "authentication_error",
               "token has expired", "401")


def token_saved():
    """Record a new token's date and clear any failure; the settings page calls this after saving."""
    from datetime import date
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    TOKEN_INFO.write_text(json.dumps({"created": date.today().isoformat()}))
    AUTH_FAILED.unlink(missing_ok=True)


def token_age_days():
    from datetime import date
    try:
        return (date.today() - date.fromisoformat(json.loads(TOKEN_INFO.read_text())["created"])).days
    except Exception:  # no token saved yet, or an unreadable file
        return None


def claude_auth_status():
    """One line when the Claude sign-in needs attention, else None."""
    if AUTH_FAILED.exists():
        return (f"Claude refused Rekall's background jobs since {AUTH_FAILED.read_text().strip()[:16]}, "
                f"so meetings aren't being captured. Sign in again: {sys.executable} {ROOT}/scripts/setup-server.py --reauth")
    age = token_age_days()
    if age is not None and age >= TOKEN_WARN_DAYS:
        return (f"Rekall's Claude sign-in is {age} days old and will expire soon. "
                f"Sign in again: {sys.executable} {ROOT}/scripts/setup-server.py --reauth")
    return None


def note_claude_result(ok, output=""):
    """Runners call this after each claude -p child: success clears the failure, an auth error records it."""
    try:
        if ok:
            AUTH_FAILED.unlink(missing_ok=True)
        elif any(e in output.lower() for e in AUTH_ERRORS):
            from datetime import datetime
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            if not AUTH_FAILED.exists():
                AUTH_FAILED.write_text(datetime.now().isoformat(timespec="minutes"))
            prompt_reauth()
    except OSError:
        pass  # bookkeeping must never fail the job


def prompt_reauth():
    """macOS dialog with a Sign in button, at most once a day. Sign in runs setup-server.py --reauth,
    which opens the Claude sign-in in the browser. Detached, so the job never waits on the dialog."""
    import subprocess, shlex, time
    if sys.platform != "darwin":
        return
    if REAUTH_PROMPTED.exists() and time.time() - REAUTH_PROMPTED.stat().st_mtime < 86400:
        return
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    REAUTH_PROMPTED.touch()
    venv = ROOT / "graph-memory/.venv/bin/python"  # has keyring; the job's own python may not
    py = venv if venv.exists() else Path(sys.executable)
    dialog = ('display dialog "Rekall needs you to sign in to Claude again, or it stops capturing meetings." '
              'with title "Rekall" buttons {"Later", "Sign in"} default button "Sign in" cancel button "Later"')
    # "Later" is the cancel button, so osascript exits non-zero and the sign-in doesn't run
    cmd = f"osascript -e {shlex.quote(dialog)} >/dev/null && {shlex.quote(str(py))} {shlex.quote(str(ROOT / 'scripts/setup-server.py'))} --reauth"
    subprocess.Popen(["/bin/sh", "-c", cmd], start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def set_secret(name, value):
    import keyring
    keyring.set_password(KEYRING_SERVICE, name, value)


if __name__ == "__main__":
    names = sys.argv[1:] or ["USER_NAME", "TIMEZONE", "VAULT", "WIKI", "SESSIONS", "ARCHIVE", "DATA", "STATE_DIR", "MONDAY_BOARD", "MONDAY_GROUP", "EMBEDDING_MODEL"]
    for n in names:
        print(globals()[n] if len(names) == 1 else f"{n}={globals()[n]}")
