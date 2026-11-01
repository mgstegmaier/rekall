"""Every digest attempt writes one outcome line to digest.log: `digest ok`, `digest dropped
<reason>` or `digest failed <exception>`. ADR-001's check counts failed over attempted."""
import importlib
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "digest"))
import headless_run  # noqa: E402

headless_run = importlib.reload(headless_run)
common, distil = headless_run.common, headless_run.distil
OUTCOME = re.compile(r"digest (ok|dropped|failed)\b")


def test_one_outcome_line_per_attempt():
    real = distil.ask, common.corpus, common.config, common.PENDING, common.LOG
    try:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            common.PENDING, common.LOG = tmp / "pending", tmp / "log"
            common.PENDING.mkdir()
            common.corpus = lambda: tmp / "notes"
            common.config = lambda: {**common.DEFAULTS, "log_dir": "sessions", "distil": False, "mode": "headless"}

            def ask(model, prompt, text):
                if "boom" in text:
                    raise TimeoutError("slow")
                return "THIN" if "thin" in text else "### What happened\nFixed."

            distil.ask = ask
            for name in ("ok", "thin", "boom"):
                (common.PENDING / f"{name}.md").write_text(f"**You:** {name}")
            headless_run.drain(min_age=0)
            lines = [m[1] for m in map(OUTCOME.search, (common.LOG / "digest.log").read_text().splitlines()) if m]
            assert sorted(lines) == ["dropped", "failed", "ok"], lines
    finally:
        distil.ask, common.corpus, common.config, common.PENDING, common.LOG = real
