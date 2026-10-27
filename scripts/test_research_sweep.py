#!/usr/bin/env python3
"""Self-check for the research sweep in fathom-pipeline.py against a throwaway vault:
which memos are pending, that the config flag turns the sweep off, and that a memo is
verified against OTHER pages rather than its own text.
Run: python3 scripts/test_research_sweep.py"""
import importlib.util
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent


def write_config(tmp, enabled):
    cfg = tmp / "rekall.toml"
    cfg.write_text(f'[user]\nname="t"\ntimezone="UTC"\n[vault]\npath="{tmp}/vault"\n'
                   f'[data]\npath="{tmp}/data"\nstate="{tmp}/state"\n'
                   f'[research]\nenabled={str(enabled).lower()}\n')
    return cfg


def load_pipeline():
    sys.modules.pop("rekall_config", None)  # under pytest an earlier test cached it with another REKALL_CONFIG
    spec = importlib.util.spec_from_file_location("fp", HERE / "fathom-pipeline.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    wiki = tmp / "vault" / "wiki"
    (wiki / "pages" / "research").mkdir(parents=True)
    (wiki / "pages" / "project").mkdir(parents=True)
    memo = wiki / "pages" / "research" / "memo-a.md"
    memo.write_text("---\ntype: research\ndate: 2026-10-26\n---\n# Memo A\n\nMeasured something.\n")
    project = wiki / "pages" / "project" / "doc-extraction.md"
    project.write_text("---\ntype: project\n---\n# Doc extraction\n\n## State\n\nRunning.\n")

    os.environ["REKALL_CONFIG"] = str(write_config(tmp, enabled=True))
    fp = load_pipeline()

    state = {"research_ingested": []}
    assert [f.name for f in fp.pending_research(state)] == ["memo-a.md"], "a new memo is pending"

    state["research_ingested"].append(fp.source_key(memo))
    assert fp.pending_research(state) == [], "an ingested memo is not pending again"

    memo.write_text(memo.read_text() + "\nMeasured something else.\n")
    assert [f.name for f in fp.pending_research(state)] == ["memo-a.md"], "an edited memo re-queues"

    # Verification must look at OTHER pages: the memo lives under pages/, so its own text
    # would otherwise satisfy the scan and verify nothing.
    ok, reason = fp.verify_ingest(["wiki/pages/research/memo-a.md"])
    assert not ok, f"unreferenced memo must fail verification, got {reason!r}"

    project.write_text(project.read_text() + "\n## Research\n\n- [[memo-a]] (measured 2026-10-26) — ok. [open]\n")
    ok, reason = fp.verify_ingest(["wiki/pages/research/memo-a.md"])
    assert ok, f"a linked memo must verify, got {reason!r}"

    # enabled = false has to be read at import, so check it in its own process
    off = subprocess.run(
        [sys.executable, "-c",
         "import importlib.util,sys;"
         f"spec=importlib.util.spec_from_file_location('fp', r'{HERE / 'fathom-pipeline.py'}');"
         "m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);"
         "print(m.pending_research({'research_ingested': []}))"],
        env={**os.environ, "REKALL_CONFIG": str(write_config(tmp, enabled=False))},
        capture_output=True, text=True)
    assert off.returncode == 0, off.stderr
    assert off.stdout.strip() == "[]", f"enabled=false must sweep nothing, got {off.stdout!r}"

print("ok: research sweep (pending, re-queue, config flag, self-excluded verification)")
