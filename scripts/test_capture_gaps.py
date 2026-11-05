"""Two capture gaps from the 2026-11-04 audit (K1, K3): the fetch window must reach back to the last
clean run, so a Friday-afternoon note survives the weekend, and a failed Monday push or a failed
ingest batch must be retried instead of dropped. Each test builds its own throwaway vault and config.
Run: python3 -m pytest scripts/test_capture_gaps.py"""
import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
FRI_LAST_RUN = datetime(2026, 10, 30, 22, 30, tzinfo=timezone.utc)   # Friday 5:30 PM CDT, the sweep's last run
FRI_NOTE = datetime(2026, 10, 30, 20, 0, tzinfo=timezone.utc)        # 3:00 PM meeting: not past the 2h lag at 5:30
MON_RUN = datetime(2026, 11, 2, 13, 30, tzinfo=timezone.utc)         # Monday 7:30 AM CST, the first run after


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, HERE / file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def fp(tmp_path, monkeypatch):
    (tmp_path / "rekall.toml").write_text(
        f'[user]\nname="t"\ntimezone="UTC"\n[vault]\npath="{tmp_path}/vault"\n'
        f'[data]\npath="{tmp_path}/data"\nstate="{tmp_path}/state"\n[monday]\nboard=1\n')
    monkeypatch.setenv("REKALL_CONFIG", str(tmp_path / "rekall.toml"))
    monkeypatch.delitem(sys.modules, "rekall_config", raising=False)
    mod = load("fp_gaps", "fathom-pipeline.py")
    for d in ("raw", "meetings", "pages/project", "pages/research", "daily-notes-archive"):
        (mod.VAULT / "wiki" / d).mkdir(parents=True)
    mod.WIKI_LOG.write_text("# Log\n")
    mod.STATE_DIR.mkdir(parents=True, exist_ok=True)
    secrets = {"MONDAY_API_TOKEN": "t", "GRANOLA_API_KEY": "k", "WORK_EMAIL": "me@x.com"}
    monkeypatch.setattr(mod, "env", lambda k, fb=None: secrets.get(k))
    monkeypatch.setattr(mod, "fetch_meetings", lambda *a: [])
    monkeypatch.setattr(mod, "notify", lambda *a, **k: None)
    yield mod
    sys.modules.pop("rekall_config", None)


def test_window_reaches_back_to_the_last_clean_run(fp):
    # The fixed 26h window from Monday 7:30 starts Sunday morning and misses Friday's 3 PM note.
    assert MON_RUN - timedelta(hours=26) > FRI_NOTE
    assert fp.window_start(MON_RUN, 26, FRI_LAST_RUN.isoformat()) <= FRI_NOTE
    assert fp.window_start(MON_RUN, 26, None) == MON_RUN - timedelta(hours=26)  # first run: the old default
    month_ago = (MON_RUN - timedelta(days=30)).isoformat()
    assert fp.window_start(MON_RUN, 26, month_ago) == MON_RUN - timedelta(days=fp.MAX_LOOKBACK_DAYS)


def test_granola_sweep_looks_back_from_its_last_run_and_records_it(fp, monkeypatch):
    gs = load("gs_gaps", "granola-sweep.py")
    monkeypatch.setattr(gs, "fp", fp)
    monkeypatch.setattr(gs, "STATE_FILE", fp.STATE_DIR / "granola-state.json")
    monkeypatch.setattr(gs, "LOCK_FILE", fp.STATE_DIR / "granola-sweep.lock")
    gs.save_state({"notes": {}, "last_success": FRI_LAST_RUN.isoformat()})
    seen = []
    monkeypatch.setattr(gs, "fetch_notes", lambda start, known: seen.append(start) or [])
    monkeypatch.setattr(sys, "argv", ["granola-sweep.py", "--no-wiki"])
    gs.main()
    assert seen[0] <= FRI_LAST_RUN - timedelta(hours=26)
    assert datetime.fromisoformat(gs.load_state()["last_success"]) > FRI_LAST_RUN


def meeting(items):
    return {"id": "m1", "title": "Planning", "dt": FRI_NOTE, "duration": 30, "participants": [],
            "summary": "s", "url": "", "action_items": [
                {"text": t, "is_mine": True, "completed": False} for t in items]}


def fake_monday(created, fail_on):
    """monday_gql stand-in: records create_item names and raises on the named item."""
    def gql(query, variables=None):
        if "groups" in query:
            return {"boards": [{"groups": [{"id": "g", "title": "Auto-Capture"}]}]}
        if "create_item" in query:
            if variables["name"] in fail_on:
                raise RuntimeError("Monday down")
            created.append(variables["name"])
            return {"create_item": {"id": str(len(created))}}
        return {"create_update": {"id": "u"}}
    return gql


def run(fp, monkeypatch, *flags):
    monkeypatch.setattr(sys, "argv", ["fathom-pipeline.py", "--no-wiki", *flags])
    fp.main()


def test_failed_monday_push_is_retried_next_run_without_duplicates(fp, monkeypatch):
    created = []
    monkeypatch.setattr(fp, "fetch_meetings", lambda *a: [meeting(["first", "second"])])
    monkeypatch.setattr(fp, "monday_gql", fake_monday(created, fail_on={"second"}))
    run(fp, monkeypatch)
    entry = fp.load_state()["meetings"]["m1"]
    assert created == ["first"] and entry["monday"] is False and "monday_pending" in entry

    monkeypatch.setattr(fp, "monday_gql", fake_monday(created, fail_on=set()))
    run(fp, monkeypatch)  # m1 is known now, so only the retry can push "second"
    entry = fp.load_state()["meetings"]["m1"]
    assert created == ["first", "second"] and entry["monday"] is True and "monday_pending" not in entry


def test_no_monday_runs_owe_nothing(fp, monkeypatch):
    # Board off or backfill: 161 such entries sit in the live state and must never be pushed later.
    monkeypatch.setattr(fp, "fetch_meetings", lambda *a: [meeting(["first"])])
    run(fp, monkeypatch, "--no-monday")
    assert "monday_pending" not in fp.load_state()["meetings"]["m1"]


def test_granola_poison_note_does_not_quarantine_its_batch(fp, monkeypatch):
    gs = load("gs_gaps2", "granola-sweep.py")
    monkeypatch.setattr(gs, "fp", fp)
    monkeypatch.setattr(gs, "STATE_FILE", fp.STATE_DIR / "granola-state.json")
    monkeypatch.setattr(gs, "LOCK_FILE", fp.STATE_DIR / "granola-sweep.lock")
    notes = {i: {"note": f"wiki/meetings/{i}.md", "merged_into": None, "ingested": False} for i in ("good", "bad")}
    gs.save_state({"notes": notes})
    monkeypatch.setattr(gs, "fetch_notes", lambda *a: [])
    monkeypatch.setattr(fp, "ingest_to_wiki", lambda batch, extra="": "wiki/meetings/bad.md" not in batch)
    monkeypatch.setattr(sys, "argv", ["granola-sweep.py"])
    monkeypatch.setattr("subprocess.run", lambda *a, **k: type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})())
    gs.main()
    state = json.loads(gs.STATE_FILE.read_text())
    assert state["notes"]["good"]["ingested"] is True
    assert state["ingest_failures"] == {"wiki/meetings/bad.md": 1}
