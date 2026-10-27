#!/usr/bin/env python3
"""Self-check for wiki-lint.py's state-drift check against a throwaway vault.
Run: python3 scripts/test_wiki_lint_state_drift.py"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    wiki = tmp / "vault" / "wiki"
    (wiki / "pages" / "project").mkdir(parents=True)
    (wiki / "index.md").write_text("x\n")
    (wiki / "log.md").write_text("x\n")
    cfg = tmp / "rekall.toml"
    cfg.write_text(f'[user]\nname="t"\ntimezone="UTC"\n[vault]\npath="{tmp}/vault"\n[data]\npath="{tmp}/data"\nstate="{tmp}/state"\n')
    env = {**os.environ, "REKALL_CONFIG": str(cfg)}

    def page(name, body, status="active"):
        (wiki / "pages" / "project" / f"{name}.md").write_text(
            f"---\ntype: project\nstatus: {status}\n---\n{body}")

    state = "## State\nShipped. (source: session 2026-09-01)\n\n"
    page("drifted", state + "## Updates\n\n### 2026-10-01 Reversed\nbody\n")
    page("bullets", state + "## Updates\n\n- 2026-09-30: reversed\n")
    page("fresh", state + "## Updates\n\n### 2026-09-15 small\nbody\n")  # exactly 14 days: not flagged
    page("same", state + "## Updates\n\n### 2026-09-01 same day\nbody\n")
    page("twostate", state + "## Updates\n\n### 2026-10-01 x\n\n## State\nNow. (source: session 2026-09-30)\n")  # 2nd State current
    page("firstbare", "## State\nno citation\n\n" + state + "## Updates\n\n### 2026-10-01 x\n")  # 1st State bare, later one cited: flagged
    page("nostate", "## Updates\n\n### 2026-10-01 only updates\nbody\n")
    page("retired", state + "## Updates\n\n### 2026-10-01 Reversed\nbody\n", status="retired")

    r = subprocess.run([sys.executable, str(HERE / "wiki-lint.py"), "--no-notify", "--verbose"],
                       env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    out = r.stdout
    assert "State drift" in out and "(3)" in out.split("State drift")[1].split("\n")[0], out
    assert "project/drifted.md: newest Update 2026-10-01, newest State citation 2026-09-01 (30 days)" in out, out
    assert "project/bullets.md: newest Update 2026-09-30, newest State citation 2026-09-01 (29 days)" in out, out
    assert "project/firstbare.md: newest Update 2026-10-01, newest State citation 2026-09-01 (30 days)" in out, out
    for ok in ("fresh", "same", "nostate", "retired", "twostate"):
        assert f"project/{ok}.md: newest Update" not in out, ok
print("ok")
