"""Checks for wispr-sweep.py: envelope parsing, note rendering, dry-run writes nothing. No real Claude."""
import importlib.util
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location("wispr_sweep", Path(__file__).parent / "wispr-sweep.py")
ws = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ws)

RAW = {"id": "w1", "title": "Data sync", "start": "2026-11-20T15:00:00Z", "end": "2026-11-20T15:30:00Z",
       "attendees": ["Michael Stegmaier", "Dana Reyes"], "summary": "- talked about X",
       "action_items": [{"text": "Send the doc", "assignee": "Michael Stegmaier"},
                        {"text": "Review it", "assignee": "Dana Reyes"}],
       "share_link": "https://notes.wisprflow.ai/shared/abc"}


def envelope(result, **kw):
    return json.dumps({"type": "result", "is_error": False, "result": result, **kw})


def test_parse_plain_and_fenced():
    assert ws.parse_envelope(envelope(json.dumps([RAW]))) == [RAW]
    assert ws.parse_envelope(envelope("```json\n" + json.dumps([RAW]) + "\n```")) == [RAW]
    assert ws.parse_envelope(envelope("[]")) == []


@pytest.mark.parametrize("stdout", [
    "not json at all",
    envelope("I could not reach the server."),
    envelope(json.dumps({"id": "x"})),                       # object, not a list
    envelope(json.dumps([{"id": "x", "title": "t"}])),       # no start
    envelope(json.dumps(["str"])),
    json.dumps({"is_error": True, "result": "[]"}),
    json.dumps({"no": "result"}),
])
def test_parse_garbage_raises(stdout):
    with pytest.raises(ValueError):
        ws.parse_envelope(stdout)


def test_run_claude_uses_flags_and_fails_on_exit(monkeypatch):
    seen = {}

    def fake(cmd, **kw):
        seen["cmd"], seen["cwd"] = cmd, kw["cwd"]
        return subprocess.CompletedProcess(cmd, 0, envelope(json.dumps([RAW])), "")
    monkeypatch.setattr(ws.subprocess, "run", fake)
    monkeypatch.setattr(ws.fp, "claude_env", lambda e: e)
    now = datetime(2026, 11, 22, tzinfo=timezone.utc)
    assert ws.run_claude(now, now) == [RAW]
    assert "--strict-mcp-config" not in seen["cmd"] and "--tools" in seen["cmd"]
    monkeypatch.setattr(ws.subprocess, "run", lambda c, **k: subprocess.CompletedProcess(c, 1, "", "boom"))
    with pytest.raises(RuntimeError):
        ws.run_claude(now, now)


def test_meeting_converts_utc_to_central_and_splits_items():
    m = ws.to_meeting(RAW)
    assert m["dt"].strftime("%Y-%m-%d %H:%M") == "2026-11-20 09:00"  # 15:00Z is 9:00 AM CST
    assert m["duration"] == 30
    assert [a["is_mine"] for a in m["action_items"]] == [True, False]


def test_note_render(tmp_path, monkeypatch):
    monkeypatch.setattr(ws.fp, "VAULT", tmp_path)
    monkeypatch.setattr(ws.fp, "MEETINGS", tmp_path / "wiki" / "meetings")
    ws.fp.MEETINGS.mkdir(parents=True)
    # late-evening UTC meeting: the Central date is the day before
    m = ws.to_meeting({**RAW, "start": "2026-11-21T03:30:00Z", "end": "2026-11-21T04:00:00Z"})
    rel = ws.write_wispr_note(m)
    assert rel == "wiki/meetings/2026-11-20-data-sync.md"
    text = (tmp_path / rel).read_text()
    for want in ["source: wispr-flow", "generated: {by: wispr-sweep", "date: 2026-11-20", "type: meeting",
                 "**Date:** 2026-11-20 at 9:30 PM", "**Recording:** [Data sync](https://notes.wisprflow.ai/shared/abc)",
                 "## Summary", "- talked about X", "## Action Items", "### Mine", "- [ ] Send the doc",
                 "### Others", "- Dana Reyes: Review it"]:
        assert want in text, want
    assert ws.write_wispr_note(m) is None  # exists


def test_append_section_once(tmp_path):
    p = tmp_path / "n.md"
    p.write_text("# n\n\nbody\n")
    m = ws.to_meeting(RAW)
    assert ws.append_wispr_section(p, m) is True
    assert ws.append_wispr_section(p, m) is False
    assert p.read_text().count(ws.SECTION) == 1


def test_dry_run_writes_nothing(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(ws.fp, "VAULT", tmp_path)
    monkeypatch.setattr(ws.fp, "MEETINGS", tmp_path / "wiki" / "meetings")
    ws.fp.MEETINGS.mkdir(parents=True)
    monkeypatch.setattr(ws, "STATE_FILE", tmp_path / "state" / "wispr-state.json")
    monkeypatch.setattr(ws, "LOCK_FILE", tmp_path / "state" / "wispr-sweep.lock")
    monkeypatch.setattr(ws, "run_claude", lambda s, u: [RAW])
    monkeypatch.setattr(sys, "argv", ["wispr-sweep.py", "--dry-run"])
    before = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*") if p.is_file() and p.name != "wispr-sweep.lock")
    ws.main()
    after = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*") if p.is_file() and p.name != "wispr-sweep.lock")
    assert before == after == []
    assert not (tmp_path / "state" / "wispr-state.json").exists()


def test_fetch_failure_exits_nonzero_without_state(tmp_path, monkeypatch):
    monkeypatch.setattr(ws, "STATE_FILE", tmp_path / "wispr-state.json")
    monkeypatch.setattr(ws, "LOCK_FILE", tmp_path / "wispr-sweep.lock")

    def bad(s, u):
        raise ValueError("garbage")
    monkeypatch.setattr(ws, "run_claude", bad)
    monkeypatch.setattr(sys, "argv", ["wispr-sweep.py"])
    with pytest.raises(SystemExit) as e:
        ws.main()
    assert e.value.code == 1 and not (tmp_path / "wispr-state.json").exists()
