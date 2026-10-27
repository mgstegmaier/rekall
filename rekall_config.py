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
# Annual-review evidence miner (scripts/wins-mine.py): work repos, git author, work markers, page tag.
WINS = _cfg.get("wins", {})
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
    """env made ready for a claude -p child of ours, changed in place and returned.

    ANTHROPIC_API_KEY goes: Doppler injects it, it overrides the subscription login, and the call
    then fails "Invalid API key" or bills the API (2026-09-24). MEMORY_STARTER_CHILD tells our own
    recall hook and SessionEnd digest to skip this session. The stored token is added: the settings
    page saves it (claude setup-token), so scheduled jobs run without an interactive login. Without
    one the child falls back to the CLI's own login, as before."""
    env.pop("ANTHROPIC_API_KEY", None)
    env["MEMORY_STARTER_CHILD"] = "1"
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
               "token has expired", "401", "failed to authenticate", "oauth session expired")


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


def run_claude(cmd, env=None, **kw):
    """Run one claude -p child to completion, the one way every runner does it: env through
    claude_env, stdout and stderr both captured (the CLI prints its errors to stdout), the sign-in
    marker set or cleared. Returns the CompletedProcess, or None when the CLI couldn't authenticate,
    which is the machine's fault and not the input's, so callers stop rather than count it.
    fathom-pipeline streams its child instead and uses claude_env and note_claude_result directly."""
    import subprocess
    env = claude_env(dict(os.environ if env is None else env))
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", **kw)
    out = proc.stdout + proc.stderr
    # ponytail: output is only searched for auth wording on a failure, since a good answer can say
    # "401"; --output-format json reports a failure as is_error with exit 0
    failed = proc.returncode != 0 or '"is_error":true' in proc.stdout.replace(" ", "")
    note_claude_result(not failed, out)
    if failed and any(e in out.lower() for e in AUTH_ERRORS):
        return None
    return proc


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


# Sweep freshness. The hook asks, on every prompt, whether a sweep has landed recently *while you
# were actually at the keyboard*. Both halves are counted in scheduled slots rather than elapsed
# hours, so a night's sleep costs nothing: the 19:15-07:15 gap holds no slots at all.
FATHOM_STATE = STATE_DIR / "fathom-pipeline-state.json"
PRESENCE = STATE_DIR / "hook-presence.json"
SWEEP_HOURS = range(7, 20)  # ponytail: mirrors com.heckatron.fathom-pipeline; change both together
SWEEP_MINUTE = 15
STALE_SLOTS = 3             # three missed runs inside the window before the hook says anything
PRESENCE_GAP = 90 * 60      # a quiet stretch longer than this means you were away, not just idle


def sweep_slots(start, end):
    """How many scheduled sweeps fall in (start, end], in local time."""
    if start is None or end <= start:
        return 0
    from datetime import datetime, time as dt_time, timedelta
    from zoneinfo import ZoneInfo
    tz = ZoneInfo(TIMEZONE)
    start, end = start.astimezone(tz), end.astimezone(tz)
    n, day = 0, start.date()
    while day <= end.date():
        for h in SWEEP_HOURS:
            slot = datetime.combine(day, dt_time(h, SWEEP_MINUTE), tzinfo=tz)
            if start < slot <= end:
                n += 1
        day += timedelta(days=1)
    return n


def sweep_stale(last_success, streak_start, now):
    """True when sweeps are overdue AND you have been present long enough for that to mean
    something. The second half is what keeps a long weekend or an overnight sleep quiet: you may
    have missed 39 slots with the lid shut, but your current stretch of use has missed none, and
    launchd's catch-up run gets its chance before anything is said."""
    if last_success is None:
        return False  # nothing has ever succeeded; a fresh install is not a fault to report
    return (sweep_slots(last_success, now) >= STALE_SLOTS
            and sweep_slots(streak_start, now) >= STALE_SLOTS)


def note_presence(now):
    """Record this prompt and return the start of the current unbroken stretch of use. A gap
    longer than PRESENCE_GAP means the machine was off or asleep, so the stretch restarts."""
    start = now
    try:
        d = json.loads(PRESENCE.read_text())
        from datetime import datetime
        if (now - datetime.fromisoformat(d["last_seen"])).total_seconds() <= PRESENCE_GAP:
            start = datetime.fromisoformat(d["streak_start"])
    except Exception:
        pass  # first run, or an unreadable file: this prompt starts the stretch
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        PRESENCE.write_text(json.dumps({"last_seen": now.isoformat(), "streak_start": start.isoformat()}))
    except OSError:
        pass  # bookkeeping must never break the prompt
    return start


def sweep_status():
    """One line when sweeps have gone quiet while you were working, else None. Unlike the auth
    flag this latches nothing: a successful run moves last_success forward and the line stops
    appearing on its own."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    streak = note_presence(now)
    try:
        last = json.loads(FATHOM_STATE.read_text()).get("last_success")
        last = datetime.fromisoformat(last) if last else None
    except Exception:
        return None
    if not sweep_stale(last, streak, now):
        return None
    from zoneinfo import ZoneInfo
    return (f"Rekall's meeting sweep hasn't completed since {last.astimezone(ZoneInfo(TIMEZONE)):%b %d %H:%M} "
            f"({sweep_slots(last, now)} scheduled runs missed), so the wiki may be behind. "
            f"Check the job is loaded: launchctl list | grep fathom")


def set_secret(name, value):
    import keyring
    keyring.set_password(KEYRING_SERVICE, name, value)


if __name__ == "__main__":
    names = sys.argv[1:] or ["USER_NAME", "TIMEZONE", "VAULT", "WIKI", "SESSIONS", "ARCHIVE", "DATA", "STATE_DIR", "MONDAY_BOARD", "MONDAY_GROUP", "EMBEDDING_MODEL"]
    for n in names:
        print(globals()[n] if len(names) == 1 else f"{n}={globals()[n]}")
