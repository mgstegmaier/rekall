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
FNS = ("subst_args", "render", "render_file", "place", "unplace")
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


def place(env, src="skills/wiki", fn="place", **extra):
    r = sh(env, f'subst_args && {fn} "$REPO/{src}"', **extra)
    assert r.returncode == 0, r.stderr
    return r.stdout


def paths(env, src="skills/wiki"):
    return Path(env["HOME"]) / ".claude" / src, Path(env["REPO"]) / ".installed" / src


def same(a, b):
    return subprocess.run(["diff", "-rq", str(a), str(b)], capture_output=True).returncode == 0


def tree_sum(d):
    return sorted((str(p.relative_to(d)), p.read_bytes()) for p in Path(d).rglob("*") if p.is_file())


def test_fresh_place_installs_the_copy_and_its_record(inst):
    dst, rec = paths(inst)
    assert place(inst).startswith(f"installed {dst}")
    text = (dst / "SKILL.md").read_text()
    assert inst["VAULT"] in text and 'vault="my-vault"' in text and "__" not in text.replace("__init__", "")
    assert same(dst, rec)


def test_second_place_is_unchanged_and_leaves_the_copy_alone(inst):
    dst, _ = paths(inst)
    place(inst)
    before = (dst / "SKILL.md").stat().st_mtime_ns
    assert place(inst).startswith(f"unchanged {dst}")
    assert (dst / "SKILL.md").stat().st_mtime_ns == before


def test_changed_source_updates_an_untouched_copy(inst):
    dst, rec = paths(inst)
    place(inst)
    with open(Path(inst["REPO"]) / "skills" / "wiki" / "SKILL.md", "a") as f:
        f.write("\nnew line\n")
    assert place(inst).startswith(f"updated {dst}")
    assert "new line" in (dst / "SKILL.md").read_text() and same(dst, rec)


def test_changed_vault_updates_an_untouched_copy(inst, tmp_path):
    dst, _ = paths(inst)
    place(inst)
    moved = str(tmp_path / "elsewhere" / "other-vault")
    assert place(inst, VAULT=moved, VAULT_NAME="other-vault").startswith(f"updated {dst}")
    assert moved in (dst / "SKILL.md").read_text()


def test_an_edited_copy_is_kept(inst):
    dst, _ = paths(inst)
    place(inst)
    with open(Path(inst["REPO"]) / "skills" / "wiki" / "SKILL.md", "a") as f:
        f.write("\nupstream change\n")
    with open(dst / "SKILL.md", "a") as f:
        f.write("\nmy edit\n")
    mine = tree_sum(dst)
    out = place(inst)
    assert out.startswith(f"kept {dst}: you changed it"), out
    assert f"mv {dst} {inst['REPO']}/.installed/backup/wiki && bash {inst['REPO']}/install.sh" in out
    assert tree_sum(dst) == mine


def test_a_foreign_file_is_left_as_is(inst):
    dst, rec = paths(inst, "commands/fathom-sync.md")
    dst.parent.mkdir(parents=True)
    dst.write_text("the owner's own command\n")
    out = place(inst, "commands/fathom-sync.md")
    assert out.startswith(f"left as is: {dst} was not installed by rekall"), out
    assert dst.read_text() == "the owner's own command\n" and not rec.exists()


@pytest.mark.parametrize("dangling", [False, True])
def test_a_symlink_is_left_as_is(inst, tmp_path, dangling):
    dst, _ = paths(inst)
    dst.parent.mkdir(parents=True)
    dst.symlink_to(tmp_path / "gone" if dangling else Path(inst["REPO"]) / "skills" / "wiki")
    before = tree_sum(Path(inst["REPO"]) / "skills")
    for fn in ("place", "unplace"):
        assert place(inst, fn=fn).startswith(f"left as is: {dst} is a link")
    assert dst.is_symlink() and tree_sum(Path(inst["REPO"]) / "skills") == before


def test_a_copy_equal_to_the_render_with_a_stale_record_is_unchanged(inst):
    dst, rec = paths(inst)
    place(inst)
    (rec / "SKILL.md").write_text("stale\n")
    assert place(inst).startswith(f"unchanged {dst}")
    assert same(dst, rec)


def test_unplace_removes_an_untouched_copy_and_keeps_an_edited_one(inst):
    dst, rec = paths(inst)
    place(inst)
    assert place(inst, fn="unplace") == "" and not dst.exists() and not rec.exists()
    place(inst)
    with open(dst / "SKILL.md", "a") as f:
        f.write("\nmy edit\n")
    assert place(inst, fn="unplace").startswith(f"kept {dst}: you changed it")
    assert dst.exists()


def test_no_installed_file_hardcodes_the_state_folder_or_the_vault():
    files = subprocess.run(["git", "ls-files", "launchd/*", "windows/*", "skills/**", "commands/**", "hooks.json",
                            "*.sh"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    assert files
    bad = [f"{f}:{i}" for f in files
           for i, line in enumerate((ROOT / f).read_text(encoding="utf-8").splitlines(), 1)
           if (".config/rekall" in line or "heck-db" in line)
           # the corporate CA bundle is config the user supplies, not state, and doesn't move
           and not (f == "commands/fathom-sync.md" and "ca-bundle.pem" in line)]
    assert not bad, bad
