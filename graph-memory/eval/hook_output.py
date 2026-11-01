"""What the recall hook emits for a prompt, as the harness would see it.

Runs recall_hook.main() in-process on a fake stdin, so the early filters, the
header, the notices and the budgets are the hook's own. Nothing here is paid.
"""
import contextlib
import io
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

MEMORY = re.compile(r"^\[(.+?) § (.*?)\]\n(.*)$", re.S)
GRAPH = re.compile(r"^(.*) -\[(.*?)\]-> (.*)  \((.*)\)$")


def emit(prompt):
    """The hook's JSON output for this prompt, or None when it prints nothing."""
    import recall_hook

    out, old = io.StringIO(), sys.stdin
    sys.stdin = io.StringIO(json.dumps({"prompt": prompt}))
    try:
        with contextlib.redirect_stdout(out):
            recall_hook.main()
    finally:
        sys.stdin = old
    text = out.getvalue().strip()
    return json.loads(text) if text else None


def items(output):
    """(kind, label, excerpt, predicate) per injected item; kind is "memory" or "graph".

    Notices and the header are skipped. This parses the hook's own format, so a
    change to it fails test_eval_harness.py instead of silently dropping rows.
    """
    ctx = ((output or {}).get("hookSpecificOutput") or {}).get("additionalContext", "")
    found = []
    for part in ctx.split("\n\n"):
        if part.startswith("Wiki graph:"):
            for line in part.splitlines()[1:]:
                m = GRAPH.match(line)
                if m:
                    s, p, t, doc = m.groups()
                    found.append(("graph", doc, f"{s} -[{p}]-> {t}", p))
        else:
            m = MEMORY.match(part)
            if m:
                found.append(("memory", f"{m[1]} § {m[2]}", m[3], ""))
    return found
