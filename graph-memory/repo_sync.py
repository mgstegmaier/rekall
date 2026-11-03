"""Keep a bare mirror of each GitHub repo listed under [repos] in rekall.toml.

Runs at 07:00 and 13:00 from repo-sync.sh (launchd/com.rekall.repo-sync.plist). Each mirror sits at
<data>/repos/<name>.git with every GitHub branch under origin/* and HEAD pointing at
origin/<branch>, so Claude reads current main with `git -C <mirror> show origin/main:<path>`.
Nothing in a mirror is ever executed, and the job never touches rag.db, the vault or your clones.

    repo_sync.py          sync every configured repo; exit 1 if any failed
    repo_sync.py --list   one tab-separated line per repo: name, mirror, branch, last good sync

State, keyed by repo name, goes to <state>/repo-sync-state.json; the recall hook reads it for its
STALE line. A failure logs `FAILED repo=<name> step=<step>: <error>` and keeps last_ok_at.
"""

import importlib.util
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import rekall_config  # noqa: E402
from rekall_config import REPO_SYNC_STATE, STATE_DIR, find_secret  # noqa: E402

LOCK = STATE_DIR / "repo-sync.lock"
TIMEOUT = 300  # seconds per git call; a hung fetch must not hold the lock for ever
# gh's login (or GH_TOKEN) reaches git through gh's credential helper, never through the URL,
# where it would persist in the mirror's config. The empty helper first clears any others.
CRED = ["-c", "credential.helper=", "-c", "credential.helper=!gh auth git-credential"]


def run(cmd, timeout=TIMEOUT):
    """Every git and gh call. No prompt can wait for a user who isn't there. Tests replace this."""
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    token = find_secret("GH_TOKEN")
    if token:
        env["GH_TOKEN"] = token
    return subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=timeout, check=True)


def git(mirror, *args):
    return run(["git", *CRED, "-C", str(mirror), *args]).stdout.strip()


def sync_mirror(repo):
    """Create or update one mirror; return the head commit of origin/<branch>. One code path for
    a new and an existing mirror, so a changed remote or branch in rekall.toml takes effect."""
    m, branch = repo["mirror"], repo["branch"]
    if not m.exists():
        m.parent.mkdir(parents=True, exist_ok=True)
        run(["git", "init", "--bare", "--quiet", str(m)])
        git(m, "remote", "add", "origin", repo["url"])
    git(m, "remote", "set-url", "origin", repo["url"])
    git(m, "config", "remote.origin.fetch", "+refs/heads/*:refs/remotes/origin/*")
    git(m, "symbolic-ref", "HEAD", f"refs/remotes/origin/{branch}")
    git(m, "fetch", "--prune", "--quiet", "origin")
    return git(m, "rev-parse", f"refs/remotes/origin/{branch}^{{commit}}")


def load_state():
    try:
        return json.loads(REPO_SYNC_STATE.read_text())
    except (OSError, ValueError):
        return {}


def save_state(state):
    REPO_SYNC_STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = REPO_SYNC_STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True))
    tmp.replace(REPO_SYNC_STATE)


def prune(state, repos):
    """Drop state entries for repos no longer in config. Their mirrors stay on disk, so adding a
    repo back costs no re-clone."""
    names = {r["name"] for r in repos}
    for name in [n for n in state if n not in names]:
        del state[name]


def list_repos():
    state = load_state()
    for r in rekall_config.repos():
        print("\t".join([r["name"], str(r["mirror"]), r["branch"], state.get(r["name"], {}).get("last_ok_at") or ""]))


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def error_text(e):
    if isinstance(e, subprocess.CalledProcessError):
        msg = (e.stderr or e.stdout or "").strip().splitlines()
        return msg[-1][:300] if msg else f"exit {e.returncode}"
    return f"{type(e).__name__}: {e}"[:300]


def load_lock():
    spec = importlib.util.spec_from_file_location("fathom_pipeline", HERE.parent / "scripts" / "fathom-pipeline.py")
    fp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fp)
    return fp.acquire_lock


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if "--list" in argv:
        list_repos()
        return 0
    repos = rekall_config.repos()
    if not repos:
        print("repo_sync: [repos] is off or lists no repo; nothing to do")
        return 0
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    lock = load_lock()(LOCK)  # bound for the whole run: a dropped handle closes and frees the flock
    if lock is None:
        print("repo_sync: skipped: already running")
        return 0
    state = load_state()
    prune(state, repos)
    failed = 0
    for r in repos:
        s = state.setdefault(r["name"], {"head": None, "indexed": None, "fetched_at": None,
                                          "last_ok_at": None, "last_error": None})
        try:
            s["head"] = sync_mirror(r)
            s["fetched_at"] = s["last_ok_at"] = now_iso()
            s["last_error"] = None
            print(f"ok repo={r['name']} head={s['head'][:12]}")
        except Exception as e:  # one repo's failure never stops the others
            s["last_error"] = f"fetch: {error_text(e)}"
            print(f"FAILED repo={r['name']} step=fetch: {error_text(e)}")
            failed += 1
    save_state(state)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
