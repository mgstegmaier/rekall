"""The recall hook skips prompts the harness wrote and still serves typed ones that follow a reminder block."""
import io
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import recall_hook  # noqa: E402

HARNESS = [
    "<task-notification>\n<task-id>1</task-id></task-notification>",
    "<system-reminder>The task tools haven't been used.</system-reminder>",
    "<cross-session-message from=\"x\">hi</cross-session-message>",
    "<command-message>wiki is running</command-message>",
    "Another Claude session sent a message:\n<agent-message>done</agent-message>",
    "[Cross-session idle notice] \"Build the research KB\" is idle.",
    "Tool loaded.",
    "This session is being continued from a previous conversation that ran out of context.",
    "Base directory for this skill: /x/y\n\n# Skill",
    "<system-reminder>a</system-reminder>\n<system-reminder>b</system-reminder>",
]


def run(monkeypatch, prompt):
    monkeypatch.setattr(recall_hook, "BROKEN", None)
    monkeypatch.setattr(recall_hook, "DB", Path(__file__))  # is_file() is all main() checks
    monkeypatch.setattr(recall_hook, "hits", lambda q: [("[pages/x.md § Y]", "the cutover target")])
    monkeypatch.setattr(recall_hook, "graph_facts", lambda q: [])
    monkeypatch.setattr(recall_hook, "claude_auth_status", lambda: None, raising=False)
    monkeypatch.setattr(recall_hook, "sweep_status", lambda: None, raising=False)
    monkeypatch.delenv("MEMORY_STARTER_CHILD", raising=False)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"prompt": prompt})))
    out = io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)
    recall_hook.main()
    return out.getvalue()


@pytest.mark.parametrize("prompt", HARNESS)
def test_harness_prompt_injects_nothing(monkeypatch, prompt):
    assert run(monkeypatch, prompt) == ""


def test_typed_question_after_reminder_still_injects(monkeypatch):
    prompt = "<system-reminder>ctx</system-reminder>\nWhat is the cutover target on the billing page?"
    assert "the cutover target" in run(monkeypatch, prompt)


def test_plain_prompt_still_injects(monkeypatch):
    assert "the cutover target" in run(monkeypatch, "what is the cutover target")
