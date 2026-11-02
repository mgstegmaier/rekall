"""R-recall-4 / R-recall-11 / R-cost-8: readers survive a missing or mismatched index.
Stubbed model, temp index, no network."""
import io
import json
import os
import sqlite3
import subprocess
import sys
import types
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mcp_server  # noqa: E402
import recall_hook  # noqa: E402
import search  # noqa: E402
from test_ranking import make_db  # noqa: E402


def test_search_wiki_without_index_creates_nothing(tmp_path, monkeypatch):
    db = tmp_path / "rag.db"
    monkeypatch.setattr(recall_hook, "DB", db)
    monkeypatch.setattr(mcp_server, "DB", db)
    out = mcp_server.search_wiki("anything")
    assert not db.exists() and "reindex.sh" in out, out


def test_graph_recall_without_index_creates_nothing(tmp_path, monkeypatch):
    import graph_recall
    monkeypatch.setattr(graph_recall, "DB", tmp_path / "rag.db")
    with pytest.raises(sqlite3.OperationalError):
        graph_recall.recall("anything")
    assert not (tmp_path / "rag.db").exists()


def test_mismatched_model_skips_meaning_leg_but_keeps_strong_keyword_hit(tmp_path, monkeypatch):
    path = tmp_path / "rag.db"
    body = "SNOW-1234 tracks the key rotation"
    db = make_db(path, [(1, "pages/t.md", "Open", body, body)])
    db.execute("INSERT INTO vectors VALUES (1, ?)", (np.array([1, 0], dtype=np.float32).tobytes(),))
    db.execute("INSERT INTO meta VALUES ('model', 'some/other-model')")
    db.commit()
    db.close()

    def boom(*a, **k):
        raise AssertionError("stale-model path reached the model or the vectors")
    monkeypatch.setitem(sys.modules, "fastembed", types.SimpleNamespace(TextEmbedding=boom))
    monkeypatch.setattr(search, "embedding_model", boom)
    monkeypatch.setattr(search.np, "vstack", boom)
    ro = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    assert search.meaning_leg(ro, "SNOW-1234") is None
    ro.close()
    monkeypatch.setattr(recall_hook, "DB", path)
    assert [l for l, _ in recall_hook.hits("what about SNOW-1234")] == ["[pages/t.md § Open]"]


def test_hook_never_downloads(tmp_path, monkeypatch):
    path = tmp_path / "rag.db"
    db = make_db(path, [(1, "pages/t.md", "Open", "SNOW-1234 tracks it", "SNOW-1234 tracks it")])
    db.execute("INSERT INTO vectors VALUES (1, ?)", (np.array([1, 0], dtype=np.float32).tobytes(),))
    db.commit()
    db.close()
    calls = []

    def fake(**kw):
        calls.append(kw)
        raise OSError("not cached")
    monkeypatch.setitem(sys.modules, "fastembed", types.SimpleNamespace(TextEmbedding=fake))
    monkeypatch.setattr(search, "MODEL_DIR", tmp_path / "no-model")
    monkeypatch.setattr(search, "ALLOW_DOWNLOAD", True)
    search.embedding_model.cache_clear()
    monkeypatch.setattr(recall_hook, "DB", path)
    with pytest.raises(OSError):
        recall_hook.hits("SNOW-1234")
    search.embedding_model.cache_clear()
    assert calls and all(c.get("local_files_only") for c in calls), calls


def run_main(monkeypatch, capsys, prompt):
    monkeypatch.delenv("MEMORY_STARTER_CHILD", raising=False)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"prompt": prompt})))
    recall_hook.main()
    return capsys.readouterr().out


def test_search_failure_keeps_graph_facts_and_health_notice(tmp_path, monkeypatch, capsys):
    db = tmp_path / "rag.db"
    make_db(db, [(1, "a.md", "S", "x", "x")]).close()
    monkeypatch.setattr(recall_hook, "DB", db)
    monkeypatch.setattr(recall_hook, "hits", lambda q, section=None: (_ for _ in ()).throw(RuntimeError("model init")))
    monkeypatch.setattr(recall_hook, "graph_facts", lambda p: [("Qval", "owns", "Tobias", "pages/q.md")])
    monkeypatch.setattr(recall_hook, "claude_auth_status", lambda: "signed out.")
    monkeypatch.setattr(recall_hook, "sweep_status", lambda: None)
    monkeypatch.setattr(recall_hook, "log", lambda r: None)
    out = json.loads(run_main(monkeypatch, capsys, "tell me about Qval"))
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert "Qval -[owns]-> Tobias" in ctx and "signed out" in ctx, out


def test_rejected_prompts_never_import_search():
    code = (
        "import io, json, sys, tempfile, pathlib\n"
        f"sys.path.insert(0, {str(Path(__file__).resolve().parent)!r})\n"
        "import recall_hook\n"
        "recall_hook.DB = pathlib.Path(tempfile.mkdtemp()) / 'rag.db'; recall_hook.DB.touch()\n"
        "for p in ('go', 'Thanks!', '<task-notification>x</task-notification>'):\n"
        "    sys.stdin = io.StringIO(json.dumps({'prompt': p})); recall_hook.main()\n"
        "print(sorted(m for m in ('search', 'numpy', 'fastembed') if m in sys.modules))\n")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=os.environ.copy())
    assert r.stdout.strip() == "[]", r
