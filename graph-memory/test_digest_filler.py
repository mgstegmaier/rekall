"""headless_run.main: a THIN reply, or one with no ### heading, never reaches the day file. The
staged text moves to pending/dropped/, out of drain()'s reach, and digest.log says why. A real
entry still lands. Run: python graph-memory/test_digest_filler.py"""
import importlib
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "digest"))
import headless_run  # noqa: E402

headless_run = importlib.reload(headless_run)  # test_digest_drain stubs main() in the shared pytest process
common, distil = headless_run.common, headless_run.distil
real = distil.ask, common.corpus, common.config, common.PENDING, common.LOG

with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    common.PENDING, common.LOG = tmp / "pending", tmp / "log"
    common.PENDING.mkdir()
    common.corpus = lambda: tmp / "notes"
    common.config = lambda: {**common.DEFAULTS, "log_dir": "sessions", "distil": False}

    for name, reply in (("thin.md", "THIN"), ("filler.md", "Session's over and already wrapped up.")):
        staged = common.PENDING / name
        staged.write_text("**You:** hello")
        distil.ask = lambda model, prompt, payload, reply=reply: reply
        headless_run.main(staged)
        assert not staged.exists() and (common.PENDING / "dropped" / name).exists(), name
    assert not (tmp / "notes" / "sessions").exists(), "no filler reached a day file"
    assert (common.LOG / "digest.log").read_text().count("moved to dropped/") == 2

    staged = common.PENDING / "real.md"
    staged.write_text("**You:** fix the build")
    distil.ask = lambda model, prompt, payload: "### What happened\nThe build was fixed."
    headless_run.main(staged)
    assert "The build was fixed." in next((tmp / "notes" / "sessions").iterdir()).read_text()
    assert [p.name for p in common.PENDING.glob("*.md")] == [], "drain() has nothing left to retry"

distil.ask, common.corpus, common.config, common.PENDING, common.LOG = real
print("ok")
