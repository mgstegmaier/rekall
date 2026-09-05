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
