"""Fathom pipeline capture: nested raw files, same-title meetings, the research write boundary,
and the two Windows paths. Each test builds its own throwaway vault and config.
Run: python3 -m pytest scripts/test_pipeline_capture.py"""
import hashlib
import importlib.util
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

HERE = Path(__file__).resolve().parent


@pytest.fixture
def fp(tmp_path, monkeypatch):
    (tmp_path / "rekall.toml").write_text(
        f'[user]\nname="t"\ntimezone="UTC"\n[vault]\npath="{tmp_path}/vault"\n'
        f'[data]\npath="{tmp_path}/data"\nstate="{tmp_path}/state"\n')
    monkeypatch.setenv("REKALL_CONFIG", str(tmp_path / "rekall.toml"))
    monkeypatch.delitem(sys.modules, "rekall_config", raising=False)
    spec = importlib.util.spec_from_file_location("fp_capture", HERE / "fathom-pipeline.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for d in ("raw", "meetings", "pages/project", "pages/research", "daily-notes-archive"):
        (mod.VAULT / "wiki" / d).mkdir(parents=True)
    mod.WIKI_LOG.write_text("# Log\n")
    monkeypatch.setattr(mod, "fetch_meetings", lambda *a: [])
    yield mod
    sys.modules.pop("rekall_config", None)


def run_main(fp, monkeypatch, *flags):
    batches = []
    monkeypatch.setattr(fp, "ingest_to_wiki", lambda batch, extra="": batches.append(list(batch)) or True)
    monkeypatch.setattr(sys, "argv", ["fathom-pipeline.py", "--no-monday", *flags])
    fp.main()
    return [s for b in batches for s in b]


def test_nested_raw_files_keep_their_relative_paths(fp, monkeypatch):
    raw = fp.VAULT / "wiki" / "raw"
    for rel in ("a/b.md", "c/b.md", ".hidden/h.md"):
        (raw / rel).parent.mkdir(parents=True, exist_ok=True)
        (raw / rel).write_text(f"# {rel}\n")
    sent = run_main(fp, monkeypatch)
    assert sorted(sent) == ["wiki/raw/a/b.md", "wiki/raw/c/b.md"]
    keys = fp.load_state()["raw_ingested"]
    assert sorted(k.split(":")[0] for k in keys) == ["a/b.md", "c/b.md"]


def test_legacy_top_level_keys_are_not_reingested(fp, monkeypatch):
    raw = fp.VAULT / "wiki" / "raw"
    (raw / "bare.md").write_text("# bare\n")
    (raw / "hashed.md").write_text("# hashed\n")
    h = hashlib.sha256((raw / "hashed.md").read_bytes()).hexdigest()[:16]
    fp.save_state({"meetings": {}, "raw_ingested": ["bare.md", f"hashed.md:{h}"], "research_ingested": []})
    assert run_main(fp, monkeypatch) == []


def test_research_memos_keep_name_hash_keys(fp):
    memo = fp.RESEARCH_DIR / "memo-a.md"
    memo.write_text("# Memo\n")
    key = f"memo-a.md:{hashlib.sha256(memo.read_bytes()).hexdigest()[:16]}"
    assert fp.source_key(memo) == key
    assert fp.pending_research({"research_ingested": [key]}) == []


def test_same_title_meetings_get_their_own_notes(fp, monkeypatch):
    dt = datetime(2026, 11, 2, 9, 0, tzinfo=ZoneInfo("UTC"))
    mk = lambda i: {"id": i, "title": "Standup", "dt": dt, "duration": 15, "participants": [],
                    "summary": f"summary {i}", "action_items": [], "url": ""}
    monkeypatch.setattr(fp, "fetch_meetings", lambda *a: [mk("1111111111"), mk("2222222222")])
    run_main(fp, monkeypatch, "--no-wiki")
    notes = {i: e["note"] for i, e in fp.load_state()["meetings"].items()}
    assert len(set(notes.values())) == 2
    for i, n in notes.items():
        assert f"summary {i}" in (fp.VAULT / n).read_text()


def test_today_skeleton_survives_the_windows_crt(fp):
    class WinDT(datetime):
        def strftime(self, fmt):
            if "%-" in fmt:
                raise ValueError("Invalid format string")
            return super().strftime(fmt)
    dt = WinDT(2026, 11, 1, 9, 0)
    assert "# Sunday, November 1, 2026" in fp._today_skeleton("2026-11-01", dt)


# ── research write boundary ─────────────────────────────────

MEMO = "wiki/pages/research/memo-a.md"
PROJECT = "---\ntype: project\n---\n# Doc extraction\n\n## State\n\nRunning.\n\n## Related pages\n\n- x\n"


@pytest.fixture
def research(fp, monkeypatch):
    v = fp.VAULT / "wiki"
    (v / "pages/research/memo-a.md").write_text("---\ntype: research\nproject: doc-extraction\ntags:\n  - x\n---\n# Memo\n")
    (v / "pages/project/doc-extraction.md").write_text(PROJECT)

    def run(agent):
        monkeypatch.setattr(fp, "ingest_to_wiki", lambda batch, extra="": (agent(), True)[1])
        return fp.ingest_research([MEMO], "x")
    return fp, run, v / "pages/project/doc-extraction.md", v / "pages/research/memo-a.md", v / "log.md"


def test_research_extra_state_edit_fails_the_batch_and_is_kept(research):
    fp, run, proj, memo, log = research
    assert run(lambda: proj.write_text(PROJECT.replace("Running.", "Done."))) is False
    assert proj.read_text() == PROJECT.replace("Running.", "Done.")


def test_research_created_page_fails_the_batch_but_is_not_deleted(research):
    fp, run, proj, memo, log = research
    new = fp.VAULT / "wiki/pages/project/new.md"
    assert run(lambda: new.write_text("# new\n")) is False
    assert new.exists()


def test_research_concurrent_writers_outside_pages_are_left_alone(research):
    fp, run, proj, memo, log = research
    (fp.VAULT / "wiki/sessions").mkdir()
    old = fp.VAULT / "wiki/sessions/2026-11-01.md"
    old.write_text("digest\n")
    new = fp.VAULT / "wiki/sessions/2026-11-02.md"
    raw = fp.VAULT / "wiki/raw/drop.md"
    edited = PROJECT.replace("## Related pages", "## Research\n\n- [[memo-a]] evidence.\n\n## Related pages")

    def agent():
        new.write_text("new session\n")
        old.write_text("digest\nappended\n")
        raw.write_text("dropped\n")
        proj.write_text(edited)
    assert run(agent) is True
    assert new.read_text() == "new session\n" and old.read_text() == "digest\nappended\n" and raw.exists()


def test_research_never_writes_after_the_verdict(research, monkeypatch):
    fp, run, proj, memo, log = research
    real = fp.research_violations

    def late_writer(*a):
        bad = real(*a)
        proj.write_text("Mike's later edit\n")  # lands after the verdict; nothing may overwrite it
        return bad
    monkeypatch.setattr(fp, "research_violations", late_writer)
    assert run(lambda: proj.write_text(PROJECT.replace("Running.", "Done."))) is False
    assert proj.read_text() == "Mike's later edit\n"


def test_research_never_rewrites_log(research):
    fp, run, proj, memo, log = research
    assert run(lambda: log.write_text("# replaced\n")) is False
    assert log.read_text() == "# replaced\n"


def test_research_memo_edit_fails_the_batch_and_is_kept(research):
    fp, run, proj, memo, log = research
    assert run(lambda: memo.write_text("# changed\n")) is False
    assert memo.read_text() == "# changed\n"


def test_research_valid_run_with_log_append_is_accepted(research):
    fp, run, proj, memo, log = research
    edited = PROJECT.replace("## Related pages", "## Research\n\n- [[memo-a]] (2026-11-01) evidence. [open]\n\n## Related pages")

    def agent():
        proj.write_text(edited)
        log.write_text(log.read_text() + "- research ingest\n")
    assert run(agent) is True
    assert proj.read_text() == edited and log.read_text().endswith("- research ingest\n")


def test_research_line_under_existing_section_is_accepted(research):
    fp, run, proj, memo, log = research
    proj.write_text(PROJECT.replace("## Related pages", "## Research\n\n- old line\n\n## Related pages"))
    cur = proj.read_text()
    assert run(lambda: proj.write_text(cur.replace("- old line\n", "- old line\n- [[memo-a]] new\n"))) is True


# ── Windows ─────────────────────────────────────────────────

def test_claude_signin_on_windows_shows_the_paste_form(fp, monkeypatch):
    spec = importlib.util.spec_from_file_location("setup_server_nt", HERE / "setup-server.py")
    ss = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ss)
    monkeypatch.setattr(ss.os, "name", "nt")
    monkeypatch.setitem(sys.modules, "fcntl", None)  # None makes `import` raise ImportError
    monkeypatch.setitem(sys.modules, "termios", None)
    monkeypatch.setattr(ss.shutil, "which", lambda n: "/bin/claude")
    ss.claude_signin()
    assert ss.CLAUDE["state"] == "failed" and "claude setup-token" in ss.CLAUDE["error"]
