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


def test_drain_gives_up_after_three_failures():
    real = headless_run.main, common.corpus, common.config, common.PENDING, common.LOG, headless_run.STRIKES
    try:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            _setup(tmp)
            calls = []

            def boom(staged):
                calls.append(staged.name)
                raise RuntimeError("model broke")

            headless_run.main = boom
            staged = common.PENDING / "s-20261030-103500.md"
            staged.write_text("**You:** x")
            for _ in range(4):
                headless_run.drain(min_age=0)
            assert calls == [staged.name] * 3, calls
            assert not staged.exists() and (common.PENDING / "failed" / staged.name).read_text() == "**You:** x"
            tags = [m[1] for m in map(OUTCOME.search, (common.LOG / "digest.log").read_text().splitlines()) if m]
            assert tags == ["failed"] * 3, "one outcome tag per attempt, none for the move"
    finally:
        headless_run.main, common.corpus, common.config, common.PENDING, common.LOG, headless_run.STRIKES = real
