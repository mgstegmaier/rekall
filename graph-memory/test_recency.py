"""Recency weighting: build_index.chunk_date picks a chunk's date in the
documented order, and search.fuse ranks the newer of two equal-scoring chunks
first while leaving undated chunks and pre-upgrade indexes alone.
Run: python3 graph-memory/test_recency.py"""
import sqlite3
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_index import chunk_date  # noqa: E402
from search import fuse, recency  # noqa: E402

TODAY = date(2026, 10, 18)

# chunk_date: newest of citations and filename prefix, then frontmatter, else None
assert chunk_date("x (source: [[2026-09-04]]) y [[2026-10-07-standup]]", "pages/a.md",
                  {"date": "2026-08-01"}, TODAY) == "2026-10-07"
assert chunk_date("cites the future [[2027-01-01]]", "pages/a.md", {"date": "2026-08-01"}, TODAY) == "2026-08-01"
assert chunk_date("no cites", "meetings/2026-02-04-all-rad-standup.md", {"date": "2026-08-01"}, TODAY) == "2026-02-04"
assert chunk_date("no cites", "sessions/2026-08-31.md", {}, TODAY) == "2026-08-31"
assert chunk_date("see [[2026-08-01-kickoff]]", "sessions/2026-10-17.md", {}, TODAY) == "2026-10-17"
assert chunk_date("no cites", "pages/a.md", {"date": '"2026-08-24"'}, TODAY) == "2026-08-24"
assert chunk_date("no cites", "pages/a.md", {"date": "someday"}, TODAY) is None
assert chunk_date("no cites", "pages/a.md", {}, TODAY) is None

# recency multiplier: 1.0 today, 0.95 at one half-life, never below the floor
assert recency("2026-10-18", TODAY) == 1.0
assert abs(recency("2026-07-20", TODAY) - 0.95) < 1e-9
assert recency("2016-01-01", TODAY) >= 0.9

db = sqlite3.connect(":memory:")
db.execute("CREATE TABLE chunks (id INTEGER PRIMARY KEY, date TEXT)")
db.executemany("INSERT INTO chunks VALUES (?, ?)",
               [(1, "2026-02-01"), (2, "2026-10-10"), (3, None), (4, "not-a-date")])

# 1 and 2 tie (each first in one leg); the newer one, 2, wins with a db
tie = {"keyword": [1], "meaning": [2]}
assert fuse(tie)[0] == [1, 2]  # no db: plain fusion, insertion order breaks the tie
assert fuse(tie, db, TODAY)[0] == [2, 1]
# undated 3 and malformed 4 keep their unweighted score, so they outrank old 1
legs = {"keyword": [1, 3], "meaning": [2, 4]}
ranked, _ = fuse(legs, db, TODAY)
assert ranked.index(3) < ranked.index(1) and ranked.index(4) < ranked.index(1), ranked

# an index built before chunks.date: fusion still works, no weighting
old = sqlite3.connect(":memory:")
old.execute("CREATE TABLE chunks (id INTEGER PRIMARY KEY, file TEXT)")
assert fuse(legs, old, TODAY)[0] == fuse(legs)[0]

print("ok")
