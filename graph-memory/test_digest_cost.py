"""Digest cost limits: headless_run.main writes an entry through the real distil.ask and its json
envelope (R-cost-2), and drain() gives a staged file three non-auth failures, then moves it to
pending/failed/ (R-cost-5)."""
import importlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "digest"))
import headless_run  # noqa: E402

headless_run = importlib.reload(headless_run)
common, distil = headless_run.common, headless_run.distil
OUTCOME = re.compile(r"digest (ok|dropped|failed)\b")


def _setup(tmp):
    common.PENDING, common.LOG = tmp / "pending", tmp / "log"
    common.PENDING.mkdir()
    common.corpus = lambda: tmp / "notes"
    common.config = lambda: {**common.DEFAULTS, "log_dir": "sessions", "distil": False, "mode": "headless"}
    headless_run.STRIKES = tmp / "state" / "digest-strikes.json"


def test_main_writes_an_entry_from_the_json_envelope():
    real = distil.ask, common.corpus, common.config, common.PENDING, common.LOG, distil.run_claude
    usage = getattr(distil, "USAGE_LOG", None)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            _setup(tmp)
            distil.USAGE_LOG = tmp / "usage.jsonl"
            out = json.dumps({"is_error": False, "result": "### What happened\nFixed it.\n", "usage": {"input_tokens": 9}})
            distil.run_claude = lambda argv, **kw: subprocess.CompletedProcess(argv, 0, out, "")
            importlib.reload(distil)  # other tests leave a stub in distil.ask; this one needs the real call
            distil.USAGE_LOG = tmp / "usage.jsonl"
            distil.run_claude = lambda argv, **kw: subprocess.CompletedProcess(argv, 0, out, "")
            staged = common.PENDING / "s.md"
            staged.write_text("**You:** fix it")
            headless_run.main(staged)
            assert "Fixed it." in next((tmp / "notes" / "sessions").glob("*.md")).read_text()
            assert len(distil.USAGE_LOG.read_text().splitlines()) == 1
    finally:
        distil.ask, common.corpus, common.config, common.PENDING, common.LOG, distil.run_claude = real
        if usage is not None:
            distil.USAGE_LOG = usage


def _drains(errors, names, n=3):
    """Drain n times; main raises errors.get(name) for a staged name, else writes it up. Returns
    the calls per name and what ended up in pending/failed/."""
    real = headless_run.main, common.corpus, common.config, common.PENDING, common.LOG, headless_run.STRIKES
    try:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            _setup(tmp)
            calls = []

            def fake(staged):
                calls.append(staged.name)
                if staged.name in errors:
                    raise errors[staged.name]
                staged.unlink()

            headless_run.main = fake
            for _ in range(n):
                for name in names:
                    (common.PENDING / name).write_text("**You:** x")
                headless_run.drain(min_age=0)
            tags = [m[1] for m in map(OUTCOME.search, (common.LOG / "digest.log").read_text().splitlines()) if m]
            return calls, sorted(p.name for p in (common.PENDING / "failed").glob("*")), tags
    finally:
        headless_run.main, common.corpus, common.config, common.PENDING, common.LOG, headless_run.STRIKES = real


def test_drain_gives_up_on_a_lone_failing_file():
    bad = "bad-20261030-103500.md"
    calls, failed, tags = _drains({bad: distil.ClaudeExit("exit 1")}, [bad, "good-20261030-103500.md"])
    assert calls.count(bad) == 3 and failed == [bad], (calls, failed)
    assert tags.count("failed") == 3, "one outcome tag per attempt, none for the move"


def test_drain_strikes_nothing_in_an_outage():
    names = ["a-20261030-103500.md", "b-20261030-103500.md"]
    for err in (distil.ClaudeExit("overloaded"), RuntimeError("no index yet"), TimeoutError("slow")):
        calls, failed, _ = _drains({n: err for n in names}, names)
        assert len(calls) == 6 and failed == [], (err, calls, failed)


def test_run_claude_ignores_401_inside_a_json_envelope():
    import rekall_config
    out = json.dumps({"is_error": True, "result": "overloaded_error", "session_id": "a401-b", "usage": {"input_tokens": 401}})
    real = subprocess.run
    subprocess.run = lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, out, "")
    marker = rekall_config.note_claude_result
    rekall_config.note_claude_result = lambda ok, output="": None
    try:
        assert rekall_config.run_claude(["claude"]) is not None, "an overload is not a sign-in failure"
        out = json.dumps({"is_error": True, "result": "Failed to authenticate: OAuth session expired"})
        assert rekall_config.run_claude(["claude"]) is None
    finally:
        subprocess.run, rekall_config.note_claude_result = real, marker
