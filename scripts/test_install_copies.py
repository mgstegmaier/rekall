"""install.sh's substitution list, placement of skills and commands, and ownership guard.
Lifts the functions out of install.sh and runs them under bash against a temp HOME and a temp repo,
never the real HOME, ~/.claude, LaunchAgents or state folder."""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FNS = ("subst_args", "render", "render_file")
PRE = "set -u\nif sed --version >/dev/null 2>&1; then SEDI=(-i); else SEDI=(-i ''); fi\nKEPT=()\n"


def fn(name):
    src = (ROOT / "install.sh").read_text(encoding="utf-8")
    return re.search(rf"^{name}\(\) \{{.*?^\}}\n", src, re.S | re.M).group(0)


@pytest.fixture
def inst(tmp_path):
    home, repo = tmp_path / "home", tmp_path / "repo"
    home.mkdir()
    for d in ("skills", "commands", "launchd", "windows"):
        shutil.copytree(ROOT / d, repo / d)
    shutil.copy(ROOT / "hooks.json", repo / "hooks.json")
    vault = tmp_path / "vaults" / "my-vault"
    env = {"PATH": os.environ["PATH"], "HOME": str(home), "REPO": str(repo), "PY3": sys.executable,
           "PY": "/v/bin/python", "SETTINGS": str(home / ".claude" / "settings.json"),
           "STATE": str(tmp_path / "state"), "VAULT": str(vault), "VAULT_NAME": vault.name, "WIN": ""}
    return env


def sh(env, script, **extra):
    return subprocess.run(["bash", "-c", PRE + "".join(fn(n) for n in FNS) + script],
                          env={**env, **extra}, capture_output=True, text=True)


WIN_VARS = {"WIN": "1", "BASH_WIN": "C:/git/bin/bash.exe", "REPO_WIN": "C:/r", "HOME_WIN": "C:/h",
            "PY_WIN": "C:/r/py.exe"}


def test_rendered_schedules_and_hook_follow_the_state_folder(inst, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    for kind, ext, extra in (("launchd", "plist", {}), ("windows", "xml", WIN_VARS)):
        for t in sorted((ROOT / kind).glob(f"*.{ext}")):
            dst = out / t.name
            r = sh(inst, f'subst_args && render_file "$REPO/{kind}/{t.name}" "{dst}"', **extra)
            assert r.returncode == 0, (t.name, r.stderr)
            text = dst.read_text()
            assert inst["STATE"] + "/logs/" in text, t.name
            assert ".config/rekall" not in text, t.name

    merge = re.search(r"settings\(\) \{.*?<<'EOF'\n(.*?)\nEOF\n",
                      (ROOT / "install.sh").read_text(encoding="utf-8"), re.S).group(1)
    p = tmp_path / "settings.json"
    p.write_text("{}")
    subprocess.run([sys.executable, "-c", merge, "add", str(ROOT), str(p), "/v/bin/python", "Bash(x:*)",
                    inst["STATE"]], check=True)
    cmd = json.loads(p.read_text())["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"]
    assert cmd.count(inst["STATE"] + "/logs") == 3, cmd
    assert ".config/rekall" not in cmd


def test_a_leftover_placeholder_stops_render_file(inst, tmp_path):
    t = tmp_path / "t.plist"
    t.write_text("<string>__REPO__/__BOGUS__</string>")
    r = sh(inst, f'subst_args && render_file "{t}" "{tmp_path / "o"}"')
    assert r.returncode == 1, r.stderr


def test_a_quote_in_the_vault_path_stops_subst_args(inst):
    r = sh(inst, 'subst_args; echo survived', VAULT="/tmp/it's")
    assert r.returncode == 1 and "survived" not in r.stdout
    assert "VAULT=" in r.stderr


@pytest.mark.parametrize("launcher", ["graph-memory/reindex.sh", "scripts/run-wiki-lint.sh",
                                      "scripts/run-fathom-pipeline.sh"])
def test_launcher_log_follows_the_state_folder(launcher, tmp_path):
    state = tmp_path / "custom-state"
    toml = tmp_path / "rekall.toml"
    toml.write_text(f'[user]\nname="t"\ntimezone="UTC"\n[vault]\npath="{tmp_path}/vault"\n'
                    f'[data]\npath="{tmp_path}/data"\nstate="{state}"\n')
    block = re.search(r'^STATE="\$\(.*?^fi\n', (ROOT / launcher).read_text(), re.S | re.M).group(0)
    name = re.search(r'LOG="\$STATE/logs/([^"]+)"', block).group(1)
    (state / "logs").mkdir(parents=True)
    (state / "logs" / name).write_text("x\n" * 600_000)  # past the 1MB truncation threshold
    pre = (f'HERE="{ROOT / "graph-memory"}"; SCRIPT_DIR="{ROOT / "scripts"}"; '
           f'PY="{sys.executable}"; VPY="{sys.executable}"\n')
    r = subprocess.run(["bash", "-c", pre + block + 'echo "$LOG"'], capture_output=True, text=True,
                       env={**os.environ, "REKALL_CONFIG": str(toml)})
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == str(state / "logs" / name)
    assert len((state / "logs" / name).read_text().splitlines()) == 2000, "truncation hit another file"
