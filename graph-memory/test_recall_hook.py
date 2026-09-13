#!/usr/bin/env python3
"""Self-check for recall_hook.excerpt (the window lands on the query terms) and
graph_facts (typed edges pass, mentions edges are dropped).
Run: python3 graph-memory/test_recall_hook.py"""
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from recall_hook import PER_HIT, excerpt, graph_facts  # noqa: E402

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

# graph_facts: an "owns" edge reachable from a seed named in the prompt comes
# back; a "mentions" edge on the same page does not (phase 0/5, see
# docs/plans/2026-09-12-typed-wiki-graph.md).
with tempfile.TemporaryDirectory() as tmp:
    db_path = Path(tmp) / "rag.db"
    db = sqlite3.connect(db_path)
    db.executescript(
        """
        CREATE TABLE entities (id TEXT PRIMARY KEY, name TEXT, type TEXT,
                               description TEXT, source_doc TEXT);
        CREATE TABLE relations (source_id TEXT, target_id TEXT,
                                predicate TEXT, source_doc TEXT);
        CREATE TABLE aliases (entity_id TEXT, alias TEXT);
        """
    )
    db.executemany(
        "INSERT INTO entities VALUES (?,?,?,?,?)",
        [
            ("e_seed", "Widget Project", "project", "", "pages/widget-project.md"),
            ("e_owner", "Alice", "person", "", "pages/alice.md"),
            ("e_other", "Other Page", "entity", "", "pages/other-page.md"),
            ("e_far", "Far Project", "project", "", "pages/far-project.md"),
        ],
    )
    db.executemany(
        "INSERT INTO relations VALUES (?,?,?,?)",
        [
            ("e_owner", "e_seed", "owns", "pages/widget-project.md"),
            ("e_seed", "e_other", "mentions", "pages/widget-project.md"),
            # Alice also owns an unrelated project. She is a person reached at hop 1,
            # so the walk must not expand through her: Far Project stays out.
            ("e_owner", "e_far", "owns", "pages/far-project.md"),
        ],
    )
    db.commit()
    db.close()

    import graph_recall

    graph_recall.DB = db_path
    facts = graph_facts("what's going on with widget project")
    assert facts == [("Alice", "owns", "Widget Project", "pages/widget-project.md")], facts

print("ok")
