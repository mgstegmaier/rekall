"""What the recall hook emits for a prompt, as the harness would see it.

Runs recall_hook.main() in-process on a fake stdin, so the early filters, the
header, the notices and the budgets are the hook's own. Nothing here is paid.
"""
import contextlib
import io
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

MEMORY = re.compile(r"^\[(.+?) § (.*?)\]\n(.*)$", re.S)
GRAPH = re.compile(r"^(.*) -\[(.*?)\]-> (.*)  \((.*)\)$")


def emit(prompt, trace=None):
    """The hook's JSON output for this prompt, or None when it prints nothing.

    EVAL_NO_RECENCY=1 ranks without recency weighting, for an A/B. When `trace` is a
    dict, trace["legs"] gets, per hit the hook searched (the order block() trims
    from), the legs that found it, e.g. "keyword+meaning". Both work by wrapping
    search.fuse and recall_hook.hits for this one call; the hook's code is untouched.
    """
    import recall_hook
    import search

    real_fuse, real_hits = search.fuse, recall_hook.hits
    seen = {}

    def fuse(legs, db=None, today=None):
        ranked, found_by = real_fuse(legs, None if os.environ.get("EVAL_NO_RECENCY") else db, today)
        seen.update(found_by=found_by, ranked=ranked)
        return ranked, found_by

    def hits(query, *a, **kw):
        found = real_hits(query, *a, **kw)
        if trace is not None:
            # hits() returns (label, text) only; match them back to the fused rows by both
            db = sqlite3.connect(recall_hook.DB)
            try:
                by_row = {}
                for rid in seen.get("ranked", []):
                    f, sec, text = db.execute("SELECT file, section, text FROM chunks WHERE id=?", (rid,)).fetchone()
                    by_row.setdefault((f"[{f} § {sec}]", " ".join(text.split())), []).append(rid)
            finally:
                db.close()
            legs = []
            for key in found:
                rids = by_row.get(key, [])
                legs.append("+".join(seen["found_by"][rids.pop(0)]) if rids else "")
            trace["legs"] = legs
        return found

    out, old = io.StringIO(), sys.stdin
    sys.stdin = io.StringIO(json.dumps({"prompt": prompt}))
    search.fuse, recall_hook.hits = fuse, hits
    try:
        with contextlib.redirect_stdout(out):
            recall_hook.main()
    finally:
        sys.stdin = old
        search.fuse, recall_hook.hits = real_fuse, real_hits
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
