"""claude_probe and --probe in setup-server.py, with `claude` stubbed: no real CLI, no keychain."""
import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location("setup_server", ROOT / "scripts" / "setup-server.py")
ss = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ss)


def stub(monkeypatch, code, out):
    monkeypatch.setattr(ss.shutil, "which", lambda _: "/stub/claude")
    monkeypatch.setattr(ss, "claude_env", lambda env: env)  # skip the keychain lookup for the stored token
    monkeypatch.setattr(ss.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, code, out, ""))


def warning(monkeypatch, capsys, code, out):
    stub(monkeypatch, code, out)
    ss.probe_warn()
    return capsys.readouterr().out


def test_ok_reply_is_silent(monkeypatch, capsys):
    assert warning(monkeypatch, capsys, 0, "ok\n") == ""


def test_exit_zero_not_logged_in_warns(monkeypatch, capsys):
    assert "WARNING" in warning(monkeypatch, capsys, 0, "Not logged in - run /login\n")


def test_nonzero_exit_warns(monkeypatch, capsys):
    assert "WARNING" in warning(monkeypatch, capsys, 1, "boom\n")


def test_docs_name_the_step():
    for f in ("README.md", "SETUP.md"):
        assert "Sign in to Claude" in (ROOT / f).read_text(encoding="utf-8"), f
