#!/usr/bin/env python3
"""Self-check for wiki-cleanup.py against a throwaway vault: stamp, archive, orphan report.
Run: python3 scripts/test_wiki_cleanup.py"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    vault, wiki = tmp / "vault", tmp / "vault" / "wiki"
    for d in ("pages", "meetings", "raw"):
        (wiki / d).mkdir(parents=True)
    cfg = tmp / "rekall.toml"
    cfg.write_text(f'[user]\nname="t"\ntimezone="UTC"\n[vault]\npath="{vault}"\n[data]\npath="{tmp}/data"\nstate="{tmp}/state"\n')
    env = {**os.environ, "REKALL_CONFIG": str(cfg)}

    def page(rel, fm, body=""):
        (wiki / rel).write_text(f"---\n{fm}\n---\n{body}\n")

    page("pages/keep.md", "type: concept\nstatus: active", "links [[gone-page]] and [[keep]]")
    page("pages/gone-page.md", "type: entity\nstatus: archive", "links [[child]]")
    page("pages/child.md", "type: entity\nstatus: active", "no other inbound")
    page("pages/nostatus.md", "type: concept\ntitle: x")
    page("meetings/2026-01-01-standup.md", "type: meeting\ntitle: s")
    page("raw/doc.md", "status: archive", "a raw source")
    (wiki / "index.md").write_text("# Index\n\n- [[keep]] -- k\n- [[gone-page]] -- g\n- [[child]] -- c\n")
    (wiki / "log.md").write_text("# Log\n")

    def run(*args):
        r = subprocess.run([sys.executable, HERE / "wiki-cleanup.py", *args], env=env, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        return r.stdout

    out = run("--stamp", "--execute")
    assert "stamped status: active on 2 file(s)" in out, out
    assert "status: active" in (wiki / "pages/nostatus.md").read_text()
    assert (wiki / "meetings/2026-01-01-standup.md").read_text().startswith("---\ntype: meeting\nstatus: active\n")
    assert "status: archive" in (wiki / "pages/gone-page.md").read_text()  # stamp never overwrites

    out = run()  # dry-run
    assert "DRY-RUN: 2 file(s)" in out and (wiki / "pages/gone-page.md").exists(), out
    assert "[[child]]" in out and "[[keep]]" not in out.split("would-be orphans")[1], out

    out = run("--execute")
    assert (wiki / "archive/gone-page.md").exists() and (wiki / "archive/doc.md").exists()
    assert not (wiki / "pages/gone-page.md").exists() and not (wiki / "raw/doc.md").exists()
    assert "[[gone-page]]" not in (wiki / "index.md").read_text()
    assert "[[gone-page]]" in (wiki / "pages/keep.md").read_text()  # links untouched
    assert "cleanup | files archived" in (wiki / "log.md").read_text()
    assert "nothing to do" in run()
print("ok")
