#!/usr/bin/env python3
"""Self-check for wiki-type-folders.py against a throwaway vault: dry run, apply, refusals.
Run: python3 scripts/test_wiki_type_folders.py"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    pages = tmp / "vault" / "wiki" / "pages"
    (pages / "concept").mkdir(parents=True)
    cfg = tmp / "rekall.toml"
    cfg.write_text(f'[user]\nname="t"\ntimezone="UTC"\n[vault]\npath="{tmp}/vault"\n[data]\npath="{tmp}/data"\nstate="{tmp}/state"\n')
    env = {**os.environ, "REKALL_CONFIG": str(cfg)}

    def page(rel, fm):
        (pages / rel).write_text(f"---\n{fm}\n---\nbody\n")

    def run(*args):
        return subprocess.run([sys.executable, str(HERE / "wiki-type-folders.py"), *args],
                              env=env, capture_output=True, text=True)

    page("alice.md", "type: person\ntitle: Alice")
    page("rekall.md", "type: project")
    page("concept/ready.md", "type: concept")  # already placed: skipped
    page("concept/misfiled.md", "type: entity")  # wrong folder: moved

    r = run()
    assert r.returncode == 0, r.stdout + r.stderr
    assert "3 pages to move (dry run" in r.stdout, r.stdout
    assert (pages / "alice.md").exists(), "dry run must not move anything"

    r = run("--apply")
    assert r.returncode == 0, r.stdout + r.stderr
    for rel in ("person/alice.md", "project/rekall.md", "concept/ready.md", "entity/misfiled.md"):
        assert (pages / rel).exists(), rel
    assert not (pages / "alice.md").exists()
    assert "0 pages to move" in run().stdout, "second run finds nothing left to move"

    page("notype.md", "title: x")
    page("dupe.md", "type: concept")
    page("person/dupe.md", "type: person")
    r = run("--apply")
    assert r.returncode == 1 and "no `type`: notype.md" in r.stdout and "basename collision: dupe.md" in r.stdout, r.stdout
    assert (pages / "dupe.md").exists(), "a refused run moves nothing"
print("ok")
