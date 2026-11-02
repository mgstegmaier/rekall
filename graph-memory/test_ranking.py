"""R-recall-3 / R-recall-7: every candidate gets its real cosine; rare names must sit in the
chunk body, not just the FTS metadata; the keyword query is bounded. Stubbed model, temp db."""
import sqlite3
import struct
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import recall_hook  # noqa: E402
import search  # noqa: E402


def make_db(path, rows):
    """rows: (id, file, section, body, fts_text)"""
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE chunks (id INTEGER PRIMARY KEY, file TEXT, section TEXT, text TEXT, date TEXT)")
    db.execute("CREATE VIRTUAL TABLE chunks_fts USING fts5(text, file, section)")
    db.execute("CREATE TABLE vectors (id INTEGER PRIMARY KEY, vec BLOB NOT NULL)")
    db.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    for i, f, s, body, fts in rows:
        db.execute("INSERT INTO chunks VALUES (?,?,?,?,NULL)", (i, f, s, body))
        db.execute("INSERT INTO chunks_fts (rowid, text, file, section) VALUES (?,?,?,?)", (i, fts, f, s))
    db.commit()
    return db


class FakeModel:
    def embed(self, texts):
        return [np.array([1.0, 0.0], dtype=np.float32) for _ in texts]


def test_meaning_leg_scores_every_row(monkeypatch):
    fake = type(sys)("fastembed")
    fake.TextEmbedding = FakeModel
    monkeypatch.setitem(sys.modules, "fastembed", fake)
    monkeypatch.setattr(search, "embedding_model", lambda: FakeModel())
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE vectors (id INTEGER PRIMARY KEY, vec BLOB NOT NULL)")
    db.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    for i in range(1, 16):  # row 15 ranks last (cosine 0.8) but is above the 0.68 floor
        v = np.array([0.8, 0.6] if i == 15 else [1.0, 0.0], dtype=np.float32)
        db.execute("INSERT INTO vectors VALUES (?,?)", (i, v.tobytes()))
    scores = {}
    top = search.meaning_leg(db, "q", scores=scores)
    assert len(top) == 10 and 15 not in top
    assert len(scores) == 15 and abs(scores[15] - 0.8) < 1e-6


def test_outside_top_ten_candidate_is_admitted(monkeypatch, tmp_path):
    """A non-strong keyword candidate ranked outside the semantic top 10, cosine over 0.68, is kept."""
    rows = [(i, f"p{i}.md", "S", f"widget notes {i}", f"widget notes {i}") for i in range(1, 16)]
    make_db(tmp_path / "rag.db", rows).close()
    monkeypatch.setattr(recall_hook, "DB", tmp_path / "rag.db")
    monkeypatch.setattr(recall_hook, "TOP", 20)
    monkeypatch.setattr(search, "keyword_leg", lambda db, q, **kw: [15])
    fake = type(sys)("fastembed")
    fake.TextEmbedding = FakeModel
    monkeypatch.setitem(sys.modules, "fastembed", fake)
    monkeypatch.setattr(search, "embedding_model", lambda: FakeModel())
    real_db = sqlite3.connect(tmp_path / "rag.db")
    for i in range(1, 16):
        v = np.array([0.8, 0.6] if i == 15 else [1.0, 0.0], dtype=np.float32)
        real_db.execute("INSERT INTO vectors VALUES (?,?)", (i, v.tobytes()))
    real_db.commit()
    real_db.close()
    assert "[p15.md § S]" in [l for l, _ in recall_hook.hits("widget")]


def test_title_only_name_is_not_strong(tmp_path):
    rows = [(1, "pages/t.md", "Open", "the key rotation is blocked", "SNOW-1234: tickets\nthe key rotation is blocked"),
            (2, "pages/u.md", "Open", "SNOW-1234 tracks rotation", "SNOW-1234 tracks rotation")]
    db = make_db(tmp_path / "rag.db", rows)
    assert search.strong_keyword_hits(db, "what about SNOW-1234", [1, 2]) == {2}


def test_no_model_common_word_vs_rare_id(monkeypatch, tmp_path):
    rows = [(1, "pages/a.md", "S", "the migration plan", "the migration plan"),
            (2, "pages/b.md", "S", "SNOW-1234 tracks the migration", "SNOW-1234 tracks the migration")]
    make_db(tmp_path / "rag.db", rows).close()
    monkeypatch.setattr(recall_hook, "DB", tmp_path / "rag.db")
    monkeypatch.setattr(search, "meaning_leg", lambda db, q, scores=None, **kw: None)
    assert recall_hook.hits("how is the migration going") == []
    assert [l for l, _ in recall_hook.hits("how is SNOW-1234 going")] == ["[pages/b.md § S]"]


def test_keyword_query_is_bounded(tmp_path):
    db = make_db(tmp_path / "rag.db", [(1, "a.md", "S", "x", "term0 term1")])
    seen = []

    class Spy:
        def execute(self, sql, args=()):
            if "ORDER BY" in sql:
                seen.append(args[0])
            return db.execute(sql, args)

    search.keyword_leg(Spy(), " ".join(f"term{i}" for i in range(60)))
    assert seen and seen[0].count(" OR ") + 1 <= search.MAX_QUERY_TERMS


def test_unknown_terms_do_not_fill_the_cap(tmp_path):
    db = make_db(tmp_path / "rag.db", [(1, "a.md", "S", "snowflake load error", "snowflake load error")])
    q = "snowflake load error " + " ".join(f"zzq{i}" for i in range(15))
    assert search.keyword_leg(db, q) == [1]
    assert search.keyword_leg(db, " ".join(f"zzq{i}" for i in range(15))) == []


def test_diacritics_fold_in_body_check(tmp_path):
    db = make_db(tmp_path / "rag.db", [(1, "a.md", "S", "Zoë owns the rollout", "Zoë owns the rollout")])
    assert search.strong_keyword_hits(db, "ask Zoe", [1]) == {1}
