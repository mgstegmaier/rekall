#!/usr/bin/env python3
"""Self-check: a reader must not block while the indexer holds a write transaction.

Reproduces the failure in rollback-journal mode, then shows WAL fixing it.
Run: python3 graph-memory/test_db_concurrency.py
"""
import sqlite3
import tempfile
import time
from pathlib import Path

READ_TIMEOUT = 0.25  # matches recall_hook.READ_TIMEOUT


def reader(path):
    """(rows, seconds) for a short read, or (None, seconds) when the lock wins."""
    t0 = time.perf_counter()
    try:
        db = sqlite3.connect(path, timeout=READ_TIMEOUT)
        n = db.execute("SELECT count(*) FROM chunks").fetchone()[0]
        db.close()
        return n, time.perf_counter() - t0
    except sqlite3.OperationalError:
        return None, time.perf_counter() - t0


def setup(path, mode):
    db = sqlite3.connect(path)
    db.execute(f"PRAGMA journal_mode={mode}")
    db.execute("CREATE TABLE IF NOT EXISTS chunks (id INTEGER PRIMARY KEY, t TEXT)")
    db.execute("INSERT INTO chunks (t) VALUES ('committed')")
    db.commit()
    got = db.execute("PRAGMA journal_mode").fetchone()[0].lower()
    db.close()
    return got


with tempfile.TemporaryDirectory() as tmp:
    # 1. rollback journal: this is the bug, a reader is locked out
    path = str(Path(tmp) / "rollback.db")
    assert setup(path, "DELETE") == "delete"
    writer = sqlite3.connect(path)
    writer.execute("BEGIN EXCLUSIVE")
    writer.execute("INSERT INTO chunks (t) VALUES ('uncommitted')")
    rows, secs = reader(path)
    assert rows is None, f"expected the reader to be locked out, read {rows}"
    assert secs < 1.0, f"reader waited {secs:.2f}s; the timeout is not being honoured"
    writer.rollback()
    writer.close()

    # 2. WAL: same write transaction, the reader still sees the committed snapshot
    path = str(Path(tmp) / "wal.db")
    assert setup(path, "WAL") == "wal"
    writer = sqlite3.connect(path)
    writer.execute("BEGIN EXCLUSIVE")
    writer.execute("INSERT INTO chunks (t) VALUES ('uncommitted')")
    rows, secs = reader(path)
    assert rows == 1, f"reader should see 1 committed row, got {rows}"
    assert secs < READ_TIMEOUT, f"reader took {secs:.2f}s, should not have waited at all"
    writer.commit()
    assert reader(path)[0] == 2, "reader should see the row once it is committed"
    writer.close()

print("ok")


# --- release gate: a rebuild is one transaction (rekall-rebuild-safety design) ---
# Each test builds a temp corpus into a temp rag.db; the live index is never opened.
import sys  # noqa: E402
from datetime import date  # noqa: E402

import pytest  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_graph  # noqa: E402
import build_index  # noqa: E402
import search  # noqa: E402


class FixedDate(date):
    @classmethod
    def today(cls):
        return date(2026, 10, 28)  # a Wednesday: no Sunday full


class FakeModel:
    model_name = build_index.EMBEDDING_MODEL
    short = False  # True: embed one vector too few, so the count check fails

    def embed(self, texts):
        texts = list(texts)
        return [[1.0, 0.5, 0.25, 0.125] for _ in texts[:len(texts) - self.short]]


def _page(wiki, slug, title, body):
    (wiki / "pages" / f"{slug}.md").write_text(f"---\ntype: project\ntitle: {title}\n---\n\n# {title}\n\n{body}\n")


@pytest.fixture
def gate(tmp_path, monkeypatch):
    wiki = tmp_path / "wiki"
    (wiki / "pages").mkdir(parents=True)
    _page(wiki, "a", "A", "The quarterly budget lives here. See [[b]].")
    _page(wiki, "b", "B", "B links on to [[c]].")
    _page(wiki, "c", "C", "C links back to [[a]].")
    db = tmp_path / "rag.db"
    monkeypatch.setattr(build_index, "DB", db)
    monkeypatch.setattr(build_graph, "DB", db)
    monkeypatch.setattr(build_index, "DISTILLED_DIR", tmp_path / "distilled")
    model = FakeModel()
    monkeypatch.setattr(search, "embedding_model", lambda: model)
    monkeypatch.setattr(build_index, "date", FixedDate)

    def run(builder, *flags):
        monkeypatch.setattr(sys, "argv", [f"{builder.__name__}.py", "--corpus", str(wiki), *flags])
        builder.main()

    def ro_view():
        ro = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            return (
                sorted(ro.execute("SELECT rowid, text FROM chunks_fts WHERE chunks_fts MATCH 'quarterly'")),
                ro.execute("SELECT count(*) FROM vectors").fetchone()[0],
                ro.execute("SELECT count(*) FROM chunks").fetchone()[0],
                sorted(ro.execute("SELECT r.source_id, r.target_id, r.predicate FROM relations r "
                                  "JOIN entities e ON e.id IN (r.source_id, r.target_id) WHERE e.name = 'A'")),
                ro.execute("SELECT value FROM meta WHERE key='corpus'").fetchone(),
            )
        finally:
            ro.close()

    run(build_index)
    run(build_graph)
    view = ro_view()
    assert view[0] and view[1] == view[2] > 0 and view[3] and view[4], view
    return type("Gate", (), dict(wiki=wiki, db=db, model=model, run=staticmethod(run),
                                 ro_view=staticmethod(ro_view)))


def _lock_released(db):
    c = sqlite3.connect(db, timeout=1, isolation_level=None)
    try:
        c.execute("BEGIN IMMEDIATE")
        c.execute("ROLLBACK")
    finally:
        c.close()


def test_release_gate_failed_full_text_rebuild_keeps_both_indexes(gate, monkeypatch):
    before = gate.ro_view()
    calls = []
    real = build_index.file_docs

    def flaky(*a):
        calls.append(a)
        if len(calls) == 2:
            raise RuntimeError("injected")
        return real(*a)

    monkeypatch.setattr(build_index, "file_docs", flaky)
    with pytest.raises(RuntimeError, match="injected"):
        gate.run(build_index, "--full")
    assert gate.ro_view() == before
    _lock_released(gate.db)


def test_release_gate_failed_graph_rebuild_keeps_both_indexes(gate, monkeypatch):
    before = gate.ro_view()

    def boom(*a):
        raise RuntimeError("injected")

    monkeypatch.setattr(build_graph, "relation_edges", boom)
    with pytest.raises(RuntimeError, match="injected"):
        gate.run(build_graph)
    assert gate.ro_view() == before
    _lock_released(gate.db)


def test_reader_mid_rebuild_sees_last_committed_index(gate, monkeypatch):
    before = gate.ro_view()
    _page(gate.wiki, "a", "A", "The quarterly budget lives here. See [[b]] and [[c]].")
    _page(gate.wiki, "d", "D", "A quarterly review, see [[a]].")
    seen, expect = [], {}

    def wrap(module, name):
        real = getattr(module, name)

        def checked(*a):
            if not seen or seen[-1] != name:
                seen.append(name)
                assert gate.ro_view() == expect[name], f"reader saw an uncommitted {name} rebuild"
            return real(*a)

        monkeypatch.setattr(module, name, checked)

    wrap(build_index, "file_docs")
    wrap(build_graph, "relation_edges")
    expect["file_docs"] = before
    gate.run(build_index, "--full")
    expect["relation_edges"] = gate.ro_view()  # the text rebuild has committed by now
    gate.run(build_graph)
    assert seen == ["file_docs", "relation_edges"]
    after = gate.ro_view()
    assert len(after[0]) > len(before[0]) and len(after[3]) > len(before[3]), after


def test_inconsistent_index_is_never_committed(gate):
    before = gate.ro_view()
    gate.model.short = True
    with pytest.raises(RuntimeError, match="index inconsistent"):
        gate.run(build_index, "--full")
    assert gate.ro_view() == before
