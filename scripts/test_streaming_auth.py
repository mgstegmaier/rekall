"""ingest_to_wiki classifies a streamed claude result: auth failures return None and set the marker,
a non-auth exit-0 is_error returns False and leaves the marker alone, a clean result clears it.
Run: python3 -m pytest scripts/test_streaming_auth.py"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
BASE = {"type": "result", "subtype": "success", "is_error": True, "total_cost_usd": 0}
COMPACT = {"separators": (",", ":")}


def result(**kw):
    return {**BASE, **kw}


CASES = {
    "live-10-26": (json.dumps(result(result="Failed to authenticate: OAuth session expired and could not be refreshed"), **COMPACT), 0),
    "compact-error": (json.dumps(result(error="authentication_failed", result="x"), **COMPACT), 0),
    "spaced-error": (json.dumps(result(error="authentication_failed", result="x")), 0),
    "not-logged-in": (json.dumps(result(result="Not logged in. Please run /login"), **COMPACT), 0),
}


class FakeProc:
    def __init__(self, lines, rc):
        self.stdout, self.rc = iter(l + "\n" for l in lines), rc

    def wait(self):
        return self.rc

    def kill(self):
        pass


@pytest.fixture
def fp(tmp_path, monkeypatch):
    cfg = tmp_path / "rekall.toml"
    cfg.write_text(f'[user]\nname="t"\ntimezone="UTC"\n[vault]\npath="{tmp_path}/vault"\n'
                   f'[data]\npath="{tmp_path}/data"\nstate="{tmp_path}/state"\n')
    (tmp_path / "vault" / "wiki").mkdir(parents=True)
    (tmp_path / "vault" / "wiki" / "CLAUDE.md").write_text("# rules\n")
    monkeypatch.setenv("REKALL_CONFIG", str(cfg))
    sys.modules.pop("rekall_config", None)
    spec = importlib.util.spec_from_file_location("fp", HERE / "fathom-pipeline.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    import rekall_config
    monkeypatch.setattr(rekall_config, "prompt_reauth", lambda: None)  # note_claude_result looks it up here
    monkeypatch.setattr(mod, "strip_remote_images", lambda paths: None)
    return mod


def run(fp, monkeypatch, line, rc):
    monkeypatch.setattr(fp.subprocess, "Popen", lambda *a, **k: FakeProc([line], rc))
    return fp.ingest_to_wiki(["wiki/raw/a.md"])


@pytest.mark.parametrize("name", CASES)
def test_auth_failures_stop_the_run(fp, monkeypatch, name):
    import rekall_config
    line, rc = CASES[name]
    assert run(fp, monkeypatch, line, rc) is None
    assert rekall_config.AUTH_FAILED.exists()


def test_rate_limit_fails_batch_and_leaves_marker(fp, monkeypatch):
    import rekall_config
    line = json.dumps(result(result="Rate limit exceeded"), **COMPACT)
    assert run(fp, monkeypatch, line, 0) is False
    assert not rekall_config.AUTH_FAILED.exists()
    rekall_config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    rekall_config.AUTH_FAILED.write_text("2026-10-26T00:00")
    assert run(fp, monkeypatch, line, 0) is False
    assert rekall_config.AUTH_FAILED.read_text() == "2026-10-26T00:00"


def test_retried_auth_error_then_clean_result_succeeds(fp, monkeypatch):
    import rekall_config
    rekall_config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    rekall_config.AUTH_FAILED.write_text("2026-10-26T00:00")
    retry = json.dumps({"type": "system", "subtype": "api_retry", "attempt": 1, "error_status": 401,
                        "error": "authentication_failed"}, **COMPACT)
    clean = json.dumps({"type": "result", "is_error": False, "result": "ok"}, **COMPACT)
    monkeypatch.setattr(fp.subprocess, "Popen", lambda *a, **k: FakeProc([retry, clean], 0))
    assert fp.ingest_to_wiki(["wiki/raw/a.md"]) is not None
    assert not rekall_config.AUTH_FAILED.exists()


def test_clean_result_clears_marker(fp, monkeypatch):
    import rekall_config
    rekall_config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    rekall_config.AUTH_FAILED.write_text("2026-10-26T00:00")
    run(fp, monkeypatch, json.dumps({"type": "result", "is_error": False, "result": "ok"}), 0)
    assert not rekall_config.AUTH_FAILED.exists()
