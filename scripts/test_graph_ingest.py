#!/usr/bin/env python3
"""Matcher, dedupe and unmatched-is-dropped checks for graph-ingest.py. No network, no real vault.
Run directly: python3 scripts/test_graph_ingest.py"""
import importlib.util
import os
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp())
(TMP / "rekall.toml").write_text(f'[user]\nname = "T"\ntimezone = "America/Chicago"\n[vault]\npath = "{TMP}/vault"\n'
                                 f'[data]\npath = "{TMP}/data"\nstate = "{TMP}/state"\n[graph]\nenabled = true\n')
os.environ["REKALL_CONFIG"] = str(TMP / "rekall.toml")  # before import: rekall_config reads it at import time

_spec = importlib.util.spec_from_file_location("graph_ingest", Path(__file__).parent / "graph-ingest.py")
gi = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gi)

PAGE = """---
type: project
status: active
title: SignalsAI
description: Document parsing for underwriters.
monday_label: AI Platform
---
# SignalsAI

## State

V1 is live.

## Updates

Newest first.

### 2026-10-15 Older entry

- something (source: x.md).

## Related pages
"""


def page(d, name, fm, body="## State\n\nx\n"):
    (d / f"{name}.md").write_text(f"---\n{fm}\n---\n# {name}\n\n{body}")


def projects_dir():
    d = TMP / "pages"
    d.mkdir(exist_ok=True)
    (d / "signals-ai.md").write_text(PAGE)
    page(d, "doc-extraction", "type: project\nstatus: active\ntitle: Document Extraction\nmonday_label: AI Platform\n"
                              "aliases:\n  - Doc Extraction\n  - smarter reading")
    page(d, "radar", "type: project\nstatus: retired\ntitle: Radar")
    page(d, "jeffrey-gottlieb", "type: person\nstatus: active\ntitle: Jeffrey Gottlieb")
    return d


def email(subject, ids, body="We decided to run V2 on all 30k documents."):
    return {"key": "mail:conv1", "kind": "email", "name": gi.clean_subject(subject),
            "msgs": [{"id": i, "from": "Jeff Gottlieb", "date": "2026-10-16T15:00:00Z", "to": ["Mike"], "body": body} for i in ids]}


def test_matcher(projects):
    m = lambda s: gi.match(gi.clean_subject(s), projects)
    assert m("RE: SignalsAI V2 rollout") == ["signals-ai"]
    assert m("Signals AI weekly sync") == ["signals-ai"]
    assert m("fw: signals-ai: excel converter") == ["signals-ai"]
    assert m("Doc extraction benchmark list") == ["doc-extraction"]
    assert m("Smarter reading POC") == ["doc-extraction"]
    assert m("AI Platform roadmap") == [], "a Monday label two pages share must not match"
    assert m("Radar dashboard") == [], "retired pages are not targets"
    assert m("Jeffrey Gottlieb 1:1") == [], "only project pages are targets"
    assert m("Signalsaid nothing") == [], "terms match whole words only"


def test_unmatched_dropped(projects):
    state, calls = {"threads": {}}, []
    t = email("Lunch on Friday?", ["a1"], body="SignalsAI is great")  # body never read for mail matching
    assert gi.plan_thread(t, projects, state, None, ask=lambda p, k: calls.append(p) or []) is None
    assert calls == [] and state == {"threads": {}}, "unmatched thread called the model or left state"


def test_dedupe_and_validation(projects):
    state, calls = {"threads": {}}, []

    def ask(prompt, key):
        calls.append(prompt)
        return [{"page": "signals-ai", "kind": "decision", "text": "Run V2 on all 30k documents [[x]]", "msg": "m1"},
                {"page": "signals-ai", "kind": "update", "text": "made up", "msg": "m9"},       # hallucinated id
                {"page": "radar", "kind": "update", "text": "wrong page", "msg": "m1"}]         # not a candidate

    t = email("RE: SignalsAI V2 rollout", ["a1"])
    facts, msgs, ph = gi.plan_thread(t, projects, state, None, ask=ask)
    assert len(facts) == 1 and facts[0]["from"] == "Jeff Gottlieb" and facts[0]["date"] == "2026-10-16"
    b = gi.bullet(t, facts[0])
    assert b == '- Decision: Run V2 on all 30k documents x (source: email "SignalsAI V2 rollout" from Jeff Gottlieb, 2026-10-16).', b

    head = gi.heading(t, "2026-10-16")
    once = gi.insert_update(PAGE, head, [b])
    assert once.index(head) < once.index("### 2026-10-15 Older entry"), "new entry must sit above older ones"
    assert once.index("Newest first.") < once.index(head)
    assert gi.insert_update(once, head, [b]) is None, "same bullet written twice"
    gi.mark_seen(state, t, msgs, ph)

    assert gi.plan_thread(t, projects, state, None, ask=ask) is None, "re-read thread added something"
    moved = email("RE: SignalsAI V2 rollout", ["a1-moved"])  # same content, new id (folder move)
    facts2, _, _ = gi.plan_thread(moved, projects, state, None, ask=ask)
    assert facts2 == [] and len(calls) == 1, "unchanged input hash must skip the model call"

    b2 = "- A later fact (source: email \"SignalsAI V2 rollout\" from Mike, 2026-10-16)."
    twice = gi.insert_update(once, head, [b, b2])
    assert twice.count(head) == 1 and twice.index(b) < twice.index(b2) < twice.index("### 2026-10-15")


def test_updates_section_created():
    text = "---\ntype: project\n---\n# P\n\n## State\n\nx\n\n## Related pages\n\n- [[a]]\n"
    out = gi.insert_update(text, "### 2026-10-16 Email: P", ["- f (source: email \"P\" from A, 2026-10-16)."])
    assert out.index("## Updates") < out.index("### 2026-10-16") < out.index("## Related pages")


def test_setup_writes_only_graph_section():
    spec = importlib.util.spec_from_file_location("setup_server", Path(__file__).parent / "setup-server.py")
    ss = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ss)
    before = ss.CONFIG.read_text()
    saved = ss.save_config({"enabled": True, "folders": ["inbox", "bad folder!"],
                            "chats": [{"id": "19:abc@thread.v2", "name": 'Jeff "J" Gottlieb 🚀'}, {"id": "not-a-chat", "name": "x"}]})
    assert saved["enabled"] is True and saved["mail_folders"] == ["inbox"]
    assert saved["chats"] == [{"id": "19:abc@thread.v2", "name": 'Jeff "J" Gottlieb 🚀'}]
    after = ss.CONFIG.read_text()
    assert after.count("[graph]") == 1 and after.split("[graph]")[0].rstrip() == before.split("[graph]")[0].rstrip(), "other sections changed"
    ss.save_config({"enabled": False, "folders": [], "chats": []})
    assert "enabled = false" in ss.CONFIG.read_text() and ss.CONFIG.read_text().count("[graph]") == 1


def main():
    projects = gi.load_projects(projects_dir())
    assert set(projects) == {"signals-ai", "doc-extraction"}, projects
    test_matcher(projects)
    test_unmatched_dropped(projects)
    test_dedupe_and_validation(projects)
    test_updates_section_created()
    test_setup_writes_only_graph_section()
    print("ok")


if __name__ == "__main__":
    main()
