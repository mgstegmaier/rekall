#!/usr/bin/env python3
"""Self-check for the section filter: hits(query, section) keeps only chunks
under that heading, matched exactly and ignoring case, and hits(query) with no
section still returns every match.
Run: python3 graph-memory/test_section_filter.py"""
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import recall_hook  # noqa: E402
import search  # noqa: E402
from build_index import SCHEMA  # noqa: E402

chunks = [
    ("sessions/2026-11-01.md", "Decisions", "kept the cutover plan for the warehouse"),
    ("sessions/2026-11-01.md", "Open loops", "the cutover still needs a rollback test"),
    ("pages/warehouse.md", "Decision matrix", "cutover options scored"),
]
with tempfile.TemporaryDirectory() as tmp:
    db_path = Path(tmp) / "rag.db"
    db = sqlite3.connect(db_path)
    db.executescript(SCHEMA)
    for i, (file, section, text) in enumerate(chunks, start=1):
        db.execute("INSERT INTO chunks (id, file, section, start_line, end_line, text) VALUES (?,?,?,1,1,?)",
                   (i, file, section, text))
        db.execute("INSERT INTO chunks_fts (rowid, text, file, section) VALUES (?,?,?,?)", (i, text, file, section))
    db.commit()

    assert sorted(search.keyword_leg(db, "cutover")) == [1, 2, 3]
    assert search.keyword_leg(db, "cutover", section="decisions") == [1]  # no prefix: "Decision matrix" stays out
    assert search.keyword_leg(db, "cutover", section="OPEN LOOPS") == [2]
    assert search.keyword_leg(db, "cutover", section="Decision") == []
    db.close()

    real_db, real_meaning = recall_hook.DB, search.meaning_leg
    try:
        recall_hook.DB = db_path
        search.meaning_leg = lambda db, query, scores=None, section=None: None  # keyword leg only
        assert [label for label, _ in recall_hook.hits("cutover", "Decisions")] == \
            ["[sessions/2026-11-01.md § Decisions]"]
        assert recall_hook.hits("cutover") == []  # no model, no section: a common word isn't a strong hit

        # with the meaning leg on, a filtered keyword hit survives a cosine below the floor
        def low_meaning_leg(db, query, scores=None, section=None):
            scores.update({1: 0.10})
            return [1]
        search.meaning_leg = low_meaning_leg
        assert len(recall_hook.hits("cutover", "Decisions")) == 1
    finally:
        recall_hook.DB, search.meaning_leg = real_db, real_meaning

print("ok")
