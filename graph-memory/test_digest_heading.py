"""headless_run.main: an entry's heading and day file come from the staged file's name (the session
id and its close stamp), not from when the write-up ran, so a drained backlog lands where each
session happened and every heading is distinct. Run: python graph-memory/test_digest_heading.py"""
import importlib
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "digest"))
import headless_run  # noqa: E402

headless_run = importlib.reload(headless_run)  # test_digest_drain stubs main() in the shared pytest process
common, distil = headless_run.common, headless_run.distil
real = distil.ask, common.corpus, common.config

with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    common.corpus = lambda: tmp / "notes"
    common.config = lambda: {**common.DEFAULTS, "log_dir": "sessions", "distil": False}
    distil.ask = lambda model, prompt, payload: "### What happened\nWork."
    for name in ("a177508f-1c9e-4e27-b31e-bc3e12a78a30-20261024-170215.md",
                 "db2fe0ba-d122-488d-9f5e-475aba77125d-20261024-170248.md", "odd-name.md"):
        (tmp / name).write_text("**You:** hello")
        headless_run.main(tmp / name)

    day = (tmp / "notes" / "sessions" / "2026-10-24.md").read_text()
    assert "## Session 17:02 · a177508f\n" in day and "## Session 17:02 · db2fe0ba\n" in day, day
    undated = [p for p in (tmp / "notes" / "sessions").iterdir() if p.name != "2026-10-24.md"]
    assert len(undated) == 1 and "· " not in undated[0].read_text(), "an unrecognised name falls back to now"

distil.ask, common.corpus, common.config = real
print("ok")
