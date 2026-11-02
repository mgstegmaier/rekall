"""Every scheduled launcher runs its Python under [secrets] run_prefix with PYTHONUTF8=1.
Copies the launchers next to a stub interpreter that prints its environment, so nothing real runs."""
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
LAUNCHERS = ["graph-memory/reindex.sh", "scripts/run-wiki-lint.sh", "scripts/run-graph-ingest.sh",
             "scripts/run-granola-sweep.sh", "scripts/run-fathom-pipeline.sh"]
# config lookups go to the real interpreter; every other call prints what the child would see
STUB = f"""#!/bin/bash
case "$1" in *rekall_config.py) exec {sys.executable} "$@";; esac
echo "CHILD $(basename "$1") PREFIX=$REKALL_PREFIX_SEEN UTF8=$PYTHONUTF8"
"""


@pytest.mark.parametrize("rel", LAUNCHERS)
def test_every_child_sees_prefix_and_utf8(tmp_path, rel):
    t = tmp_path / "repo"
    for r in LAUNCHERS:
        (t / r).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / r, t / r)
    shutil.copy2(ROOT / "rekall_config.py", t / "rekall_config.py")
    py = t / "graph-memory/.venv/bin/python"
    py.parent.mkdir(parents=True)
    py.write_text(STUB)
    py.chmod(py.stat().st_mode | stat.S_IEXEC)
    (tmp_path / "vault" / "wiki").mkdir(parents=True)
    (tmp_path / "home").mkdir()
    (tmp_path / "rekall.toml").write_text(
        f'[user]\nname = "t"\ntimezone = "UTC"\n[vault]\npath = "{tmp_path / "vault"}"\n[data]\npath = "{tmp_path / "data"}"\n'
        '[secrets]\nrun_prefix = "env REKALL_PREFIX_SEEN=1"\n')
    # force Sunday so the lint launcher's cleanup step runs too
    shim = tmp_path / "bin"
    shim.mkdir()
    (shim / "date").write_text('#!/bin/bash\n[ "$1" = +%u ] && echo 7 || exec /bin/date "$@"\n')
    (shim / "date").chmod(0o755)
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONUTF8", "PYTHON")}
    env.update(REKALL_CONFIG=str(tmp_path / "rekall.toml"), HOME=str(tmp_path / "home"),
               PATH=f"{shim}:{os.environ['PATH']}")
    r = subprocess.run(["bash", str(t / rel)], env=env, capture_output=True, text=True, timeout=60)
    children = [l for l in r.stdout.splitlines() if l.startswith("CHILD ")]
    assert children, r.stdout + r.stderr
    for l in children:
        assert "PREFIX=1" in l and "UTF8=1" in l, l
    if rel.endswith("run-wiki-lint.sh"):
        assert [l.split()[1] for l in children] == ["wiki-lint.py", "wiki-cleanup.py"]


@pytest.mark.parametrize("rel", LAUNCHERS)
def test_path_reaches_homebrew_before_prefix(rel):
    """launchd's PATH is /usr/bin:/bin:/usr/sbin:/sbin, so a Homebrew run_prefix (doppler) needs the
    launcher to add /opt/homebrew/bin before the first job runs."""
    text = (ROOT / rel).read_text()
    path_at = next((i for i, l in enumerate(text.splitlines())
                    if l.startswith("export PATH=") and "/opt/homebrew/bin" in l), None)
    first_job = next(i for i, l in enumerate(text.splitlines()) if "$PREFIX" in l and not l.lstrip().startswith("#"))
    assert path_at is not None and path_at < first_job, rel


FAIL_STUB = f"""#!/bin/bash
case "$1" in *rekall_config.py) exec {sys.executable} "$@";; *%s) exit %d;; esac
echo "CHILD $(basename "$1")"
"""


@pytest.mark.parametrize("has_wiki,failing,rc,other", [
    (True, "build_index", 1, "build_graph"),
    (True, "build_graph", 3, "build_index"),
    (False, "build_index", 1, None),
])
def test_reindex_reports_failed_builder(tmp_path, has_wiki, failing, rc, other):
    """A failed builder logs FAILED <step> rc=<n> and makes reindex.sh exit non-zero, while the
    other builder still runs; a missing wiki folder stops the script before any build step."""
    t = tmp_path / "repo"
    (t / "graph-memory").mkdir(parents=True)
    shutil.copy2(ROOT / "graph-memory/reindex.sh", t / "graph-memory/reindex.sh")
    shutil.copy2(ROOT / "rekall_config.py", t / "rekall_config.py")
    py = t / "graph-memory/.venv/bin/python"
    py.parent.mkdir(parents=True)
    py.write_text(FAIL_STUB % (failing + ".py", rc))
    py.chmod(py.stat().st_mode | stat.S_IEXEC)
    (tmp_path / "vault").mkdir()
    if has_wiki:
        (tmp_path / "vault" / "wiki").mkdir()
    (tmp_path / "home").mkdir()
    (tmp_path / "rekall.toml").write_text(
        f'[user]\nname = "t"\ntimezone = "UTC"\n[vault]\npath = "{tmp_path / "vault"}"\n[data]\npath = "{tmp_path / "data"}"\n')
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONUTF8", "PYTHON")}
    env.update(REKALL_CONFIG=str(tmp_path / "rekall.toml"), HOME=str(tmp_path / "home"))
    r = subprocess.run(["bash", str(t / "graph-memory/reindex.sh")], env=env, capture_output=True, text=True, timeout=60)
    if has_wiki:
        assert r.returncode == 1, r.stdout + r.stderr
        assert f"FAILED {failing} rc={rc}" in r.stdout, r.stdout
        assert f"CHILD {other}.py" in r.stdout, r.stdout
    else:
        assert r.returncode == 2, r.stdout + r.stderr
        assert "FAILED config" in r.stdout, r.stdout
        assert "CHILD " not in r.stdout, r.stdout  # no step ran, build_index included
