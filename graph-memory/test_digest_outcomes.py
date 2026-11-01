"""Every digest attempt writes one outcome line to digest.log: `digest ok`, `digest dropped
<reason>` or `digest failed <exception>`. ADR-001's check counts failed over attempted."""
import importlib
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


def _run(fn, **cfg):
    real = distil.ask, common.corpus, common.config, common.PENDING, common.LOG, distil.run, distil.rebuild_index
    try:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            common.PENDING, common.LOG = tmp / "pending", tmp / "log"
            common.PENDING.mkdir()
            common.corpus = lambda: tmp / "notes"
            common.config = lambda: {**common.DEFAULTS, "log_dir": "sessions", "distil": False, "mode": "headless", **cfg}
            tags = lambda: [m[1] for m in map(OUTCOME.search, (common.LOG / "digest.log").read_text().splitlines()) if m]
            fn(tags)
    finally:
        distil.ask, common.corpus, common.config, common.PENDING, common.LOG, distil.run, distil.rebuild_index = real


def test_late_distil_error_is_one_tag():
    def body(tags):
        distil.ask = lambda *a: "### What happened\nFixed."
        distil.run = lambda *a, **k: None

        def bad(*a):
            raise OSError("disk")

        distil.rebuild_index = bad
        (common.PENDING / "a.md").write_text("**You:** hi")
        headless_run.drain(min_age=0)
        assert tags() == ["failed"]

    _run(body, distil=True)


def test_not_signed_in_is_one_failed():
    def body(tags):
        def ask(*a):
            raise distil.NotSignedIn("claude is not signed in; sign in again")

        distil.ask = ask
        (common.PENDING / "a.md").write_text("**You:** hi")
        headless_run.drain(min_age=0)
        assert tags() == ["failed"]

    _run(body)


def test_empty_file_is_dropped():
    def body(tags):
        (common.PENDING / "a.md").write_text("  \n")
        headless_run.drain(min_age=0)
        assert tags() == ["dropped"]

    _run(body)


def test_adr_greps_count_one_of_three(tmp_path):
    log = tmp_path / "digest.log"
    log.write_text(
        "2026-11-02T01:00:00 headless_run: digest ok\n"
        "2026-11-02T02:00:00 headless_run: digest dropped the model wrote 'THIN'\n"
        "2026-11-02T03:00:00 drain: digest failed TimeoutError a.md: slow\n"
    )
    count = lambda pat: int(subprocess.run(["grep", "-cE", pat, str(log)], capture_output=True, text=True).stdout)
    assert (count(" digest failed "), count(" digest (ok|dropped|failed)")) == (1, 3)


def test_adr_old_format_grep_matches_old_lines():
    adr = next(Path(__file__).resolve().parents[1].glob("docs/decisions/ADR-001*.md")).read_text()
    pat = re.search(r"grep -E '(.+?)' digest.log", adr)[1].replace("\\S", "[^ ]")
    old = ["x headless_run: a.md: TimeoutError slow", "x drain: a.md: RuntimeError boom",
           "x drain: a.md: claude is not signed in; sign in again; stopping"]
    assert all(re.search(pat, line) for line in old)
    assert not re.search(pat, "x headless_run: a.md: moved to dropped/, why")
