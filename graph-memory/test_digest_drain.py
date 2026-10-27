"""headless_run.drain: staged session digests older than ten minutes are retried oldest
first, one at a time; a sign-in failure stops the drain; session mode drains nothing.
Run: python graph-memory/test_digest_drain.py"""
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "digest"))
import headless_run  # noqa: E402

common, distil = headless_run.common, headless_run.distil

with tempfile.TemporaryDirectory() as tmp:
    common.PENDING = Path(tmp)
    common.LOG = Path(tmp) / "log"
    old = time.time() - 3600
    for name, age in (("b.md", old + 60), ("a.md", old), ("fresh.md", time.time())):
        (Path(tmp) / name).write_text("x")
        os.utime(Path(tmp) / name, (age, age))

    seen = []

    def written(staged):
        seen.append(staged.name)
        staged.unlink()

    headless_run.main = written
    common.config = lambda: {**common.DEFAULTS, "mode": "session"}
    headless_run.drain()
    assert seen == [], "session mode leaves staged text alone"

    common.config = lambda: {**common.DEFAULTS, "mode": "headless"}
    headless_run.drain()
    assert seen == ["a.md", "b.md"], f"oldest first, the fresh file left to its own run: {seen}"
    assert (Path(tmp) / "fresh.md").exists()

    for name in ("c.md", "d.md"):
        (Path(tmp) / name).write_text("x")
        os.utime(Path(tmp) / name, (old, old))
    seen.clear()

    def signed_out(staged):
        seen.append(staged.name)
        raise distil.NotSignedIn("not signed in")

    headless_run.main = signed_out
    headless_run.drain()
    assert seen == ["c.md"], f"a sign-in failure stops the drain: {seen}"
    assert (Path(tmp) / "c.md").exists() and (Path(tmp) / "d.md").exists(), "nothing is thrown away"

print("ok")
