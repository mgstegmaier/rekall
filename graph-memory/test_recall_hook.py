#!/usr/bin/env python3
"""Self-check for recall_hook.excerpt: the window lands on the query terms.
Run: python3 graph-memory/test_recall_hook.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from recall_hook import PER_HIT, excerpt  # noqa: E402

filler = "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu "

# short text comes back whole, no ellipsis
short = "a tiny section"
assert excerpt(short, ["tiny"]) == short

# no term to anchor on: the head, exactly as before the change
none = (filler * 20).strip()
assert excerpt(none, ["windows"]) == none[:PER_HIT] + "..."
assert excerpt(none, []) == none[:PER_HIT] + "..."

# the answer sits well past the head: the window must reach it
late = (filler * 12) + "the cutover target is zero legacy refs " + (filler * 12)
got = excerpt(late, ["cutover", "legacy"])
assert "cutover" in got and "legacy" in got, got
assert got.startswith("..."), got
assert len(got) <= PER_HIT + 6, len(got)  # two ellipses of slack
assert late[:PER_HIT] != got  # genuinely different from the old behaviour

# whole words only at both edges
body = got.strip(".")
assert late.split(body)[0][-1:] in ("", " "), repr(body[:20])
assert late.split(body)[1][:1] in ("", " "), repr(body[-20:])

# terms clustered late beat a lone early term
spread = "windows " + (filler * 15) + "install the windows agent on the desktop " + (filler * 6)
got = excerpt(spread, ["windows", "install", "desktop"])
assert "install" in got and "desktop" in got, got

# a term in the head keeps the head, with no leading ellipsis
early = "the cost watch threshold " + (filler * 20)
got = excerpt(early, ["cost", "threshold"])
assert not got.startswith("..."), got
assert got.endswith("..."), got

print("ok")
