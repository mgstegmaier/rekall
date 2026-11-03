"""Output shaping of the recall hook: one total budget (F-recall-6), excerpt() scoring
every occurrence (F-recall-8), the graph walk skipping predicates (F-recall-5).
Run: python3 -m pytest graph-memory/test_recall_output.py"""
import io
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import graph_recall  # noqa: E402
import recall_hook  # noqa: E402
from recall_hook import BUDGET, GRAPH_BUDGET, PER_HIT, excerpt  # noqa: E402


def emit(monkeypatch, capsys, found, facts, sweep=None, repo=None, auth=None, full=False):
    """The hook's additionalContext for stubbed hits, graph facts, sweep and repo notices
    (the whole JSON output when full is set)."""
    monkeypatch.setattr(recall_hook, "BROKEN", None, raising=False)
    monkeypatch.setattr(recall_hook, "DB", Path(__file__))  # any existing file
    monkeypatch.setattr(recall_hook, "hits", lambda q: found)
    monkeypatch.setattr(recall_hook, "graph_facts", lambda q: facts)
    monkeypatch.setattr(recall_hook, "claude_auth_status", lambda: auth)
    monkeypatch.setattr(recall_hook, "sweep_status", lambda: sweep)
    monkeypatch.setattr(recall_hook, "repo_sync_status", lambda: repo)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"prompt": "what is going on with widget project"})))
    recall_hook.main()
    out = capsys.readouterr().out
    if full:
        return json.loads(out) if out else None
    return json.loads(out)["hookSpecificOutput"]["additionalContext"]


def graph_section(ctx):
    return next(p for p in ctx.split("\n\n") if p.startswith("Wiki graph:"))


BIG_HIT = ("[pages/widget-project.md § Status]", "word " * 200)
BIG_FACT = [("Widget", "owns", "Thing", "x" * 2000)]


def test_whole_injection_stays_under_budget(monkeypatch, capsys):  # (a)
    found = [(f"[pages/p{i}.md § S]", "word " * 200) for i in range(4)]
    facts = [("Widget", "owns", f"Thing{i}", "pages/widget-project.md" + "x" * 150) for i in range(4)]
    ctx = emit(monkeypatch, capsys, found, facts, sweep="sweeps stale " + "y" * 150)
    assert "Rekall sweeps" in ctx and "Wiki graph:" in ctx and "[pages/p0.md" in ctx
    assert len(ctx) <= BUDGET, len(ctx)


def test_oversize_label_is_cut(monkeypatch, capsys):  # (b)
    ctx = emit(monkeypatch, capsys, [("[" + "f" * 2000 + " § S]", "text")], [])
    assert len(ctx) <= BUDGET, len(ctx)


def test_first_graph_fact_is_cut(monkeypatch, capsys):  # (c)
    ctx = emit(monkeypatch, capsys, [], BIG_FACT)
    assert len(graph_section(ctx)) <= GRAPH_BUDGET, len(graph_section(ctx))


def test_big_fact_and_big_hit_stay_under_budget(monkeypatch, capsys):  # (d)
    ctx = emit(monkeypatch, capsys, [BIG_HIT], BIG_FACT)
    assert len(ctx) <= BUDGET, len(ctx)
    assert "[pages/widget-project.md § Status]" in ctx


def test_excerpt_scores_every_occurrence():
    pad = "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu " * 6  # > PER_HIT apart
    text = ("quokka " + pad + "zebra " + pad + "walrus " + pad
            + "the quokka met a zebra and a walrus at the pond " + pad)
    got = excerpt(text, ["quokka", "zebra", "walrus"])
    assert all(t in got for t in ("quokka", "zebra", "walrus")), got
    assert len(pad) > PER_HIT


def test_walk_skips_predicate_inside_the_walk(tmp_path, monkeypatch):
    db = sqlite3.connect(tmp_path / "rag.db")
    db.executescript("""
        CREATE TABLE entities (id TEXT PRIMARY KEY, name TEXT, type TEXT, description TEXT, source_doc TEXT);
        CREATE TABLE relations (source_id TEXT, target_id TEXT, predicate TEXT, source_doc TEXT);
        CREATE TABLE aliases (entity_id TEXT, alias TEXT);
    """)
    db.executemany("INSERT INTO entities VALUES (?,?,?,'','')",
                   [(i, n, "project") for i, n in [("s", "Widget Project"), ("a", "Alpha Page"),
                                                    ("b", "Beta Page"), ("c", "Gamma Page")]])
    db.executemany("INSERT INTO relations VALUES (?,?,?,'doc.md')", [
        ("s", "a", "mentions"), ("s", "b", "mentions"),
        ("a", "b", "owns"),   # typed edge between two neighbours reached only through mentions
        ("s", "c", "owns"),   # typed edge touching the seed
    ])
    db.commit()
    db.close()
    monkeypatch.setattr(graph_recall, "DB", tmp_path / "rag.db")
    got = graph_recall.recall("widget project", skip=("mentions",)).triples
    assert [(s, p, t) for s, p, t, _ in got] == [("Widget Project", "owns", "Gamma Page")], got


def test_no_graph_fragment_when_hits_leave_little_room(monkeypatch, capsys):
    facts = [("Rekall", "part_of", "Wiki", "pages/rekall.md")]
    seen = set()
    for pad in range(98, 152, 4):  # four 280-char hits plus a padded label leave about 58 down to 6 chars
        found = [(f"[pages/p{i}.md § S{'x' * (pad if i == 0 else 0)}]", "word " * 200) for i in range(4)]
        ctx = emit(monkeypatch, capsys, found, facts)
        assert "[pages/p3.md" in ctx and len(ctx) <= BUDGET
        whole = "Rekall -[part_of]-> Wiki  (pages/rekall.md)" in ctx
        assert whole or "Wiki graph:" not in ctx, ctx[-80:]  # a whole fact or no section, never a fragment
        seen.add(whole)
    assert seen == {True, False}  # the sweep covers both sides of the fit


STALE = "svc: STALE, 2 runs missed, last sync Nov 01 13:01 (fetch: HTTP 403). Check the log."


def test_stale_repo_line_fits_the_budget_and_names_the_message(monkeypatch, capsys):
    found = [(f"[pages/p{i}.md § S]", "word " * 200) for i in range(4)]
    out = emit(monkeypatch, capsys, found, [], repo=STALE, full=True)
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert "Rekall repo sync: " + STALE in ctx and "[pages/p0.md" in ctx
    assert len(ctx) <= BUDGET, len(ctx)
    assert STALE in out["systemMessage"]


def test_stale_repo_line_shows_with_no_wiki_hits(monkeypatch, capsys):
    ctx = emit(monkeypatch, capsys, [], [], repo=STALE)
    assert ctx.startswith("Rekall repo sync: ")


def test_sign_in_failure_hides_the_repo_line(monkeypatch, capsys):
    ctx = emit(monkeypatch, capsys, [], [], auth="signed out", repo=STALE)
    assert "Rekall sign-in" in ctx and "Rekall repo sync" not in ctx


def test_repos_off_leaves_the_output_unchanged(monkeypatch, capsys):
    found = [("[pages/widget-project.md § Status]", "widget status " * 20)]
    out = emit(monkeypatch, capsys, found, [], repo=None, full=True)
    assert out["systemMessage"] == "memory: 1 hit" and "Rekall repo sync" not in json.dumps(out)
    assert emit(monkeypatch, capsys, [], [], repo=None, full=True) is None
