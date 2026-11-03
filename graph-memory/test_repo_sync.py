"""repo_sync.py, phase 1: bare mirrors that follow origin/<branch>, per-repo failure handling, the
lock, pruning, name checks and --list. Runs against a throwaway git repo through a file:// remote,
so it needs git but no network and no GitHub login."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import rekall_config  # noqa: E402
import repo_sync  # noqa: E402


def sh(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout.strip()


def commit(work, name, text="x"):
    (work / name).write_text(text)
    sh(work, "add", name)
    sh(work, "-c", "user.name=T", "-c", "user.email=t@example.com", "commit", "-q", "-m", f"add {name}")
    return sh(work, "rev-parse", "HEAD")


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A working repo pushed to a bare 'GitHub' remote, and [repos] pointing at it."""
    origin, work = tmp_path / "origin.git", tmp_path / "work"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(work)], check=True)
    sh(work, "remote", "add", "origin", origin.as_uri())
    commit(work, "a.md")
    sh(work, "push", "-q", "origin", "main")
    state = tmp_path / "state"

    def configure(*entries, enabled=True):
        monkeypatch.setattr(rekall_config, "REPOS", {"enabled": enabled, "repo": list(entries)})
    configure({"name": "demo", "remote": origin.as_uri()})
    monkeypatch.setattr(rekall_config, "MIRRORS", tmp_path / "data" / "repos")
    monkeypatch.setattr(rekall_config, "REPO_SYNC_STATE", state / "repo-sync-state.json")
    monkeypatch.setattr(repo_sync, "REPO_SYNC_STATE", state / "repo-sync-state.json")
    monkeypatch.setattr(repo_sync, "STATE_DIR", state)
    monkeypatch.setattr(repo_sync, "LOCK", state / "repo-sync.lock")
    monkeypatch.setattr(repo_sync, "find_secret", lambda name: None)  # never read the real keychain
    return {"origin": origin, "work": work, "state": state, "configure": configure,
            "mirror": tmp_path / "data" / "repos" / "demo.git"}


def saved(env):
    return json.loads((env["state"] / "repo-sync-state.json").read_text())


def test_first_sync_creates_the_mirror_with_head_on_origin_main(env):
    assert repo_sync.main([]) == 0
    m, head = env["mirror"], sh(env["work"], "rev-parse", "HEAD")
    assert sh(m, "rev-parse", "origin/main") == head
    assert sh(m, "rev-parse", "HEAD") == head
    assert saved(env)["demo"]["head"] == head and saved(env)["demo"]["last_ok_at"]
    assert saved(env)["demo"]["indexed"] is None


def test_second_sync_follows_new_commits_and_keeps_no_local_branches(env):
    repo_sync.main([])
    new = commit(env["work"], "b.md")
    sh(env["work"], "push", "-q", "origin", "main")
    assert repo_sync.main([]) == 0
    m = env["mirror"]
    assert sh(m, "rev-parse", "HEAD") == sh(m, "rev-parse", "origin/main") == new
    assert sh(m, "for-each-ref", "refs/heads/") == ""


def test_a_pushed_branch_appears_under_origin(env):
    sh(env["work"], "checkout", "-q", "-b", "feature")
    tip = commit(env["work"], "f.md")
    sh(env["work"], "push", "-q", "origin", "feature")
    repo_sync.main([])
    assert sh(env["mirror"], "rev-parse", "origin/feature") == tip


def test_an_unreachable_remote_records_the_error_and_keeps_last_ok(env, capsys):
    repo_sync.main([])
    good = saved(env)["demo"]
    env["configure"]({"name": "demo", "remote": "https://127.0.0.1:9/"})
    assert repo_sync.main([]) == 1
    s = saved(env)["demo"]
    assert s["last_error"] and s["last_error"].startswith("fetch:")
    assert s["last_ok_at"] == good["last_ok_at"] and s["head"] == good["head"]
    assert "FAILED repo=demo step=fetch" in capsys.readouterr().out


def test_one_failing_repo_does_not_stop_the_next(env):
    env["configure"]({"name": "bad", "remote": "https://127.0.0.1:9/"},
                     {"name": "demo", "remote": env["origin"].as_uri()})
    assert repo_sync.main([]) == 1
    assert saved(env)["demo"]["last_ok_at"] and saved(env)["bad"]["last_ok_at"] is None


def test_a_held_lock_exits_0_without_changes(env, capsys):
    env["state"].mkdir(parents=True)
    held = repo_sync.load_lock()(repo_sync.LOCK)
    assert held is not None
    assert repo_sync.main([]) == 0
    assert "already running" in capsys.readouterr().out
    assert not env["mirror"].exists() and not (env["state"] / "repo-sync-state.json").exists()
    held.close()


def test_a_repo_removed_from_config_loses_its_state_entry(env):
    env["configure"]({"name": "demo", "remote": env["origin"].as_uri()},
                     {"name": "other", "remote": env["origin"].as_uri()})
    repo_sync.main([])
    assert set(saved(env)) == {"demo", "other"}
    env["configure"]({"name": "demo", "remote": env["origin"].as_uri()})
    repo_sync.main([])
    assert set(saved(env)) == {"demo"}


@pytest.mark.parametrize("name", [".", "..", ".hidden", "a/b", ""])
def test_bad_names_are_rejected(env, name):
    env["configure"]({"name": name, "remote": "o/r"})
    with pytest.raises(ValueError):
        rekall_config.repos()


def test_a_duplicate_name_is_rejected(env):
    env["configure"]({"name": "x", "remote": "o/r"}, {"name": "x", "remote": "o/s"})
    with pytest.raises(ValueError, match="twice"):
        rekall_config.repos()


def test_remote_forms(env):
    env["configure"]({"name": "gh", "remote": "owner/name"}, {"name": "url", "remote": "file:///x", "branch": "dev"})
    gh, url = rekall_config.repos()
    assert gh["url"] == "https://github.com/owner/name" and gh["branch"] == "main"
    assert url["url"] == "file:///x" and url["branch"] == "dev"


def test_list_prints_one_tab_separated_line_per_repo(env, capsys):
    repo_sync.main([])
    capsys.readouterr()
    assert repo_sync.main(["--list"]) == 0
    (line,) = capsys.readouterr().out.splitlines()
    name, mirror, branch, last = line.split("\t")
    assert (name, mirror, branch) == ("demo", str(env["mirror"]), "main") and last


def test_list_prints_nothing_with_repos_off(env, capsys):
    env["configure"](enabled=False)
    assert repo_sync.main(["--list"]) == 0
    assert capsys.readouterr().out == ""
