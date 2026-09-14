"""search.meaning_leg's numpy scan returns the same top-10 order as a pure-Python
cosine-sim oracle on a 5-row fixture (the oracle is the old loop, kept here only,
not in search.py). Run: python3 graph-memory/test_search.py"""
import sqlite3
import struct
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from search import QUERY_PREFIX, embedding_model, meaning_leg  # noqa: E402

db = sqlite3.connect(":memory:")
db.execute("CREATE TABLE vectors (id INTEGER PRIMARY KEY, vec BLOB NOT NULL)")
db.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")

model = embedding_model()
dim = len(list(model.embed(["x"]))[0])
rng = np.random.default_rng(0)
vecs = {}
for i in range(1, 6):
    v = rng.normal(size=dim).astype(np.float32)
    v /= np.linalg.norm(v)
    vecs[i] = v
    db.execute("INSERT INTO vectors VALUES (?, ?)", (i, struct.pack(f"{dim}f", *v)))
db.commit()

query = "snowflake key rotation for dbt users"
q = list(model.embed([QUERY_PREFIX + query]))[0]
qnorm = sum(x * x for x in q) ** 0.5 or 1.0
q = [x / qnorm for x in q]

# oracle: the old pure-Python loop this change replaces
scored = [(sum(a * b for a, b in zip(q, vecs[rowid])), rowid) for rowid in vecs]
scored.sort(reverse=True)
expected = [rowid for _, rowid in scored[:10]]

got = meaning_leg(db, query)
assert got == expected, (got, expected)
print("ok")
