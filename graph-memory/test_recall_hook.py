#!/usr/bin/env python3
"""Self-check for recall_hook.excerpt (the window lands on the query terms),
graph_facts (typed edges pass, mentions edges are dropped), the
MEANING_THRESHOLD cutoff in hits(), the graph_block char cap, and the
MEMORY_STARTER_CHILD early return in main().
Run: python3 graph-memory/test_recall_hook.py"""
import io
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import recall_hook  # noqa: E402
import search  # noqa: E402
from recall_hook import GRAPH_BUDGET, MEANING_THRESHOLD, PER_HIT, excerpt, graph_block, graph_facts, hits  # noqa: E402

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

# hits(): a candidate below MEANING_THRESHOLD is dropped even though it's the
# top-fused result; one above it is kept. keyword_leg/meaning_leg/fuse are
# monkeypatched so this doesn't need a real index or a model download.
with tempfile.TemporaryDirectory() as tmp:
    db_path = Path(tmp) / "rag.db"
    db = sqlite3.connect(db_path)
    db.execute("CREATE TABLE chunks (id INTEGER PRIMARY KEY, file TEXT, section TEXT, text TEXT)")
    db.executemany(
        "INSERT INTO chunks VALUES (?,?,?,?)",
        [
            (1, "pages/qval.md", "Status", "well above threshold"),
            (2, "sessions/2026-08-31.md", "Open loops", "coincidental keyword-only match"),
        ],
    )
    db.commit()
    db.close()

    real_keyword_leg, real_meaning_leg, real_fuse = search.keyword_leg, search.meaning_leg, search.fuse
    try:
        search.keyword_leg = lambda db, query: [1, 2]

        def fake_meaning_leg(db, query, scores=None):
            if scores is not None:
                scores.update({1: 0.90, 2: 0.50})  # 2 sits below MEANING_THRESHOLD (0.68)
            return [1, 2]

        search.meaning_leg = fake_meaning_leg
        recall_hook.DB = db_path
        got = hits("qval status")
        assert [label for label, _ in got] == ["[pages/qval.md § Status]"], got

        # with the meaning leg off entirely, keyword hits pass through unfiltered
        search.meaning_leg = lambda db, query, scores=None: None
        got = hits("qval status")
        assert len(got) == 2, got
    finally:
        search.keyword_leg, search.meaning_leg, search.fuse = real_keyword_leg, real_meaning_leg, real_fuse

# graph_block: whole triples only, capped at GRAPH_BUDGET. Each line is
# ~257 chars (17 of template plus a 240-char doc path): two fit under a
# 600-char budget, a third would not, so it's dropped whole rather than cut.
long_doc = "x" * 240
facts = [("A", "owns", "B", long_doc), ("C", "owns", "D", long_doc), ("E", "owns", "F", long_doc)]
lines = graph_block(facts)
assert len(lines) == 2, lines  # the third would push past budget
assert graph_block([facts[0]]) == [f"A -[owns]-> B  ({long_doc})"]  # one huge triple still goes out whole

# MEMORY_STARTER_CHILD: main() prints nothing and never touches stdin
os.environ["MEMORY_STARTER_CHILD"] = "1"
try:
    old_stdin, old_stdout = sys.stdin, sys.stdout
    sys.stdin = io.StringIO()  # would raise if main() tried to read it (empty JSON)
    sys.stdout = captured = io.StringIO()
    try:
        recall_hook.main()
    finally:
        sys.stdin, sys.stdout = old_stdin, old_stdout
    assert captured.getvalue() == "", captured.getvalue()
finally:
    del os.environ["MEMORY_STARTER_CHILD"]

# open-asks button prompts skip recall; ordinary prompts that merely start alike don't
for button in ["Approved: Delete the branch?", 'For "Which board?", I pick: Platform', "Not doing this, plan around it: Run setup.py",
               'Approved with changes. Instead of "X", do this: Y', 'Answer to "What id?": 42']:
    assert recall_hook.BUTTON_PROMPT.match(button), button
for ordinary in ["Approved budget for the DV2 refactor?", "For the EDP pipeline, what broke?", "Done with snowflake, now dbt"]:
    assert not recall_hook.BUTTON_PROMPT.match(ordinary), ordinary

# Fail open, fail loud: every failure exits 0 with a "rekall unavailable" notice and a log line.
# Each case runs the hook as Claude Code does, in a subprocess, with HOME in a temp dir so the
# log lands there and never in the real ~/.config/rekall.
import subprocess  # noqa: E402

HOOK = Path(__file__).resolve().parent / "recall_hook.py"
PROMPT = json.dumps({"prompt": "what broke in the EDP pipeline"})


def run(cmd, home, env=None, shell=False):
    env = {**os.environ, "HOME": str(home), **(env or {})}
    env.pop("MEMORY_STARTER_CHILD", None)
    return subprocess.run(cmd, input=PROMPT, capture_output=True, text=True, env=env, shell=shell,
                          executable="/bin/bash" if shell else None, timeout=60)


def assert_unavailable(r, log, why):
    assert r.returncode == 0, (why, r.returncode, r.stderr)
    assert "rekall unavailable" in json.loads(r.stdout)["systemMessage"], (why, r.stdout)
    assert log.is_file() and log.read_text().strip(), (why, "no log line")


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    toml = tmp / "rekall.toml"
    state = tmp / "state"

    # missing rag.db: config loads, index absent
    toml.write_text(f'[user]\nname="t"\ntimezone="UTC"\n[vault]\npath="{tmp}/vault"\n'
                    f'[data]\npath="{tmp}/data"\nstate="{state}"\n')
    assert_unavailable(run([sys.executable, str(HOOK)], tmp, {"REKALL_CONFIG": str(toml)}),
                       state / "logs" / "hook.log", "missing rag.db")

    # search raises: rag.db exists but is not a database
    (tmp / "data").mkdir()
    (tmp / "data" / "rag.db").write_text("not sqlite")
    (state / "logs" / "hook.log").unlink()
    assert_unavailable(run([sys.executable, str(HOOK)], tmp, {"REKALL_CONFIG": str(toml)}),
                       state / "logs" / "hook.log", "search raised")

    # config missing: rekall_config sys.exits at import; the log falls back to ~/.config/rekall
    assert_unavailable(run([sys.executable, str(HOOK)], tmp, {"REKALL_CONFIG": str(tmp / "nope.toml")}),
                       tmp / ".config" / "rekall" / "logs" / "hook.log", "missing rekall.toml")

    # the settings command itself, from hooks.json, with the script and then the venv missing:
    # bare python on a missing script exits 2, which Claude Code reads as "block every prompt"
    template = json.load(open(HOOK.parents[1] / "hooks.json"))["hooks"]
    recall_cmd = template["UserPromptSubmit"][0]["hooks"][0]["command"]
    end_cmd = template["SessionEnd"][0]["hooks"][0]["command"]
    assert run([sys.executable, str(tmp / "gone.py")], tmp).returncode == 2  # the failure being guarded
    for repo, py in [(tmp / "no-repo", sys.executable), (HOOK.parents[1], str(tmp / "no-venv" / "python"))]:
        log = tmp / ".config" / "rekall" / "logs" / "hook.log"
        log.unlink(missing_ok=True)
        cmd = recall_cmd.replace("__REPO__", str(repo)).replace("__VENV_PY__", py)
        assert_unavailable(run(cmd, tmp, shell=True), log, f"settings command, repo={repo} py={py}")
        r = run(end_cmd.replace("__REPO__", str(repo)).replace("__VENV_PY__", py), tmp, shell=True)
        assert r.returncode == 0, ("session_end command", r.returncode, r.stderr)

print("ok")
