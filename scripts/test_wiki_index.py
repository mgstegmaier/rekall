#!/usr/bin/env python3
"""Self-check for wiki-index.py's frontmatter quoting against a throwaway vault.
Run: python3 scripts/test_wiki_index.py"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    wiki = tmp / "vault" / "wiki"
    (wiki / "pages" / "system").mkdir(parents=True)
    cfg = tmp / "rekall.toml"
    cfg.write_text(f'[user]\nname="t"\ntimezone="UTC"\n[vault]\npath="{tmp}/vault"\n[data]\npath="{tmp}/data"\nstate="{tmp}/state"\n')
    env = {**os.environ, "REKALL_CONFIG": str(cfg)}

    bad = wiki / "pages" / "system" / "sigma.md"
    bad.write_text("---\ntype: system\ntitle: \"Sigma\"\ndescription: Sigma at Acme: Radar results\n"
                   "date: 2026-10-22\n---\n# Sigma\n\nbody: stays unquoted\n")
    ok = wiki / "pages" / "system" / "loro.md"
    ok_text = "---\ntype: system\ntitle: Loro\ndescription: A plain sentence, no colon.\n---\nbody\n"
    ok.write_text(ok_text)

    def run(*args):
        return subprocess.run([sys.executable, str(HERE / "wiki-index.py"), *args],
                              env=env, capture_output=True, text=True)

    r = run("--dry-run")
    assert "quoted title/description frontmatter on 1 page(s) (dry-run)" in r.stdout, r.stdout + r.stderr
    assert "Acme: Radar results\n" in bad.read_text(), "dry run must not write"

    r = run()
    assert r.returncode == 0, r.stderr
    text = bad.read_text()
    assert 'description: "Sigma at Acme: Radar results"\n' in text, text
    assert 'title: "Sigma"\n' in text and "body: stays unquoted\n" in text, text
    assert ok.read_text() == ok_text, "safe values are left alone"
    assert "- [[sigma]] -- Sigma at Acme: Radar results" in (wiki / "index.md").read_text()

    try:
        import yaml
    except ImportError:  # the round-trip is a bonus; the asserts above are the check
        yaml = None
    if yaml:
        assert yaml.safe_load(text.split("---\n")[1])["description"] == "Sigma at Acme: Radar results"
print("ok")
