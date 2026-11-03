"""The staleness nudge must stay silent when the machine was simply off or asleep, and speak when
sweeps stop while you are sitting there working. Those two cases are the whole point, so they get
a test; the slot arithmetic across an overnight gap is where this would break quietly."""
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

# A throwaway config before the import, so the test runs without a real install and pins the
# timezone: slot arithmetic must not depend on where the machine happens to be.
TMP = Path(tempfile.mkdtemp())
(TMP / "rekall.toml").write_text(
    f'[user]\nname = "T"\ntimezone = "UTC"\n[vault]\npath = "{TMP}/v"\n[data]\npath = "{TMP}/d"\n')
os.environ["REKALL_CONFIG"] = str(TMP / "rekall.toml")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import rekall_config as rc  # noqa: E402

TZ = ZoneInfo(rc.TIMEZONE)


def at(day, hour, minute=0):
    """A local-time datetime on a known Monday (2026-10-26) plus `day` days."""
    return datetime(2026, 10, 26, hour, minute, tzinfo=TZ) + timedelta(days=day)


def test_slots_skip_the_overnight_gap():
    # 19:20 Monday to 07:30 Tuesday spans 12 hours but only the 07:15 run.
    assert rc.sweep_slots(at(0, 19, 20), at(1, 7, 30)) == 1
    # Inside the window the slots are hourly.
    assert rc.sweep_slots(at(0, 9, 20), at(0, 12, 30)) == 3
    # Before the first run of the day there are none.
    assert rc.sweep_slots(at(0, 5, 0), at(0, 7, 0)) == 0
    assert rc.sweep_slots(at(0, 10, 0), at(0, 10, 0)) == 0


def test_quiet_overnight_does_not_warn():
    # Laptop shut at 19:30, opened at 08:00. One slot missed, and you just got here.
    assert not rc.sweep_stale(last_success=at(0, 19, 20), streak_start=at(1, 7, 55), now=at(1, 8, 0))


def test_long_weekend_does_not_warn():
    # Off from Friday evening to Tuesday morning: 39+ slots missed, but the stretch of use is new,
    # so launchd's catch-up run gets its chance before anything is said.
    last, now = at(-3, 19, 20), at(1, 9, 0)
    assert rc.sweep_slots(last, now) > 30, "setup should look alarming on elapsed time alone"
    assert not rc.sweep_stale(last_success=last, streak_start=at(1, 8, 55), now=now)


def test_sweeps_dying_mid_workday_warns():
    # Working since 08:00, last sweep landed 09:20, now 12:30: the 10:15, 11:15 and 12:15 runs
    # never happened and you were here for all three.
    assert rc.sweep_stale(last_success=at(0, 9, 20), streak_start=at(0, 8, 0), now=at(0, 12, 30))


def test_healthy_and_fresh_install_stay_quiet():
    assert not rc.sweep_stale(last_success=at(0, 11, 20), streak_start=at(0, 8, 0), now=at(0, 12, 30))
    assert not rc.sweep_stale(last_success=None, streak_start=at(0, 8, 0), now=at(0, 23, 0))


def test_presence_streak_resets_after_a_gap(tmp_path=None):
    d = Path(tmp_path or tempfile.mkdtemp())
    original = rc.PRESENCE
    rc.PRESENCE = d / "hook-presence.json"
    try:
        first = rc.note_presence(at(0, 9, 0))
        assert first == at(0, 9, 0), "the first prompt starts the stretch"
        # A prompt 20 minutes later continues the same stretch.
        assert rc.note_presence(at(0, 9, 20)) == at(0, 9, 0)
        # A prompt the next morning starts a new one, however old the stretch looked.
        assert rc.note_presence(at(1, 8, 0)) == at(1, 8, 0)
        assert json.loads(rc.PRESENCE.read_text())["last_seen"] == at(1, 8, 0).isoformat()
    finally:
        rc.PRESENCE = original


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok  {name}")
    print("all passed")


# The repo sync reuses the sweep's rule at 07:00 and 13:00 with two slots. The sweep's own line
# must not move because of the new keyword arguments, so the cases above run unchanged.

def test_sweep_defaults_are_unchanged_by_the_new_arguments():
    a, b = at(0, 9, 20), at(0, 12, 30)
    assert rc.sweep_slots(a, b) == rc.sweep_slots(a, b, hours=rc.SWEEP_HOURS, minute=rc.SWEEP_MINUTE) == 3
    assert rc.sweep_slots(a, b, hours=(7, 13), minute=0) == 0
    assert rc.sweep_slots(at(0, 6, 0), at(0, 14, 0), hours=(7, 13), minute=0) == 2


def repo_env(monkeypatch, entry):
    """[repos] on with one repo whose state entry is `entry` (None: no state file at all)."""
    monkeypatch.setattr(rc, "REPOS", {"enabled": True, "repo": [{"name": "svc", "remote": "o/svc"}]})
    state = TMP / "repo-state.json"
    state.unlink(missing_ok=True)
    if entry is not None:
        state.write_text(json.dumps({"svc": entry}))
    monkeypatch.setattr(rc, "REPO_SYNC_STATE", state)


def ok_at(t):
    return {"head": "a" * 40, "indexed": None, "fetched_at": t.isoformat(), "last_ok_at": t.isoformat(),
            "last_error": None}


def test_repo_quiet_after_a_weekend_with_the_lid_shut(monkeypatch):
    repo_env(monkeypatch, ok_at(at(-3, 13, 1)))
    lines = rc.repo_freshness(now=at(1, 9, 0), streak=at(1, 8, 55))
    assert lines == ["svc: main @ aaaaaaa fetched, last sync Oct 23 13:01"]


def test_repo_named_after_two_missed_runs_while_working(monkeypatch):
    entry = {**ok_at(at(0, 13, 1)), "last_error": "fetch: HTTP 403"}
    repo_env(monkeypatch, entry)
    # Working since 06:30 Tuesday; the 07:00 and 13:00 runs both failed.
    monkeypatch.setattr(rc, "note_presence", lambda now: at(1, 6, 30))
    line = rc.repo_sync_status(now=at(1, 14, 0))
    assert line and line.startswith("svc: STALE, 2 runs missed, last sync Oct 26 13:01 (fetch: HTTP 403)")


def test_repo_with_no_last_ok_is_quiet_in_the_hook(monkeypatch):
    repo_env(monkeypatch, {"head": None, "indexed": None, "fetched_at": None, "last_ok_at": None,
                           "last_error": "fetch: HTTP 404"})
    assert rc.repo_sync_status() is None
    assert rc.repo_freshness(now=at(1, 14, 0), streak=at(1, 6, 0)) == ["svc: never synced (fetch: HTTP 404)"]


def test_repo_status_is_none_with_repos_off_or_no_state(monkeypatch):
    repo_env(monkeypatch, None)
    assert rc.repo_sync_status() is None
    repo_env(monkeypatch, ok_at(at(-10, 7, 0)))
    monkeypatch.setattr(rc, "REPOS", {"enabled": False})
    assert rc.repo_sync_status() is None
