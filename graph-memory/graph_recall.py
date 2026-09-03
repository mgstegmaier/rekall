"""Query the graph: seed entities from the question, walk k hops, return triples.

Pure SQLite, no model call anywhere in this file. This runs inside the prompt
hook, so it has to be deterministic and fast. Adapted from the starter's
src/recall.py: same recursive walk, pointed at rag.db's graph tables.
"""

import re
import sqlite3
import sys
import time
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from paths import DB  # noqa: E402

WALK = """
WITH RECURSIVE walk(entity_id, depth) AS (
  SELECT id, 0 FROM entities WHERE id IN ({seeds})
  UNION
  SELECT CASE WHEN r.source_id = w.entity_id
              THEN r.target_id ELSE r.source_id END,
         w.depth + 1
  FROM relations r JOIN walk w
    ON w.entity_id IN (r.source_id, r.target_id)
  WHERE w.depth < ?
)
SELECT e1.name, r.predicate, e2.name, r.source_doc,
       MIN((SELECT MIN(depth) FROM walk WHERE entity_id = r.source_id),
           (SELECT MIN(depth) FROM walk WHERE entity_id = r.target_id)) AS near
FROM relations r
JOIN entities e1 ON e1.id = r.source_id
JOIN entities e2 ON e2.id = r.target_id
WHERE r.source_id IN (SELECT entity_id FROM walk)
  AND r.target_id IN (SELECT entity_id FROM walk)
ORDER BY near
"""


@dataclass
class Facts:
    triples: list  # (source, predicate, target, source_doc)
    ms: float

    def as_text(self) -> str:
        if not self.triples:
            return f"no graph matches ({self.ms:.0f} ms)"
        lines = [f"{s} -[{p}]-> {t}  ({doc})" for s, p, t, doc in self.triples]
        return "\n".join(lines)


def _seeds(db, question):
    """An entity is a seed when its name or an alias appears in the question."""
    q = question.lower()
    found = {}
    rows = list(db.execute("SELECT id, name FROM entities"))
    rows += list(db.execute("SELECT entity_id, alias FROM aliases"))
    for entity_id, text in rows:
        if len(text) < 3:  # ponytail: 2-char names seed on noise
            continue
        if re.search(rf"\b{re.escape(text.lower())}\b", q):
            found[entity_id] = True
    return list(found)


def recall(question, hops=2, top_k=8):
    t0 = time.perf_counter()
    db = sqlite3.connect(DB)
    try:
        seeds = _seeds(db, question)
        if not seeds:
            return Facts([], (time.perf_counter() - t0) * 1000)
        marks = ",".join("?" * len(seeds))
        rows = db.execute(WALK.format(seeds=marks), (*seeds, hops)).fetchall()
        triples = [(s, p, t, doc) for s, p, t, doc, _ in rows[:top_k]]
        return Facts(triples, (time.perf_counter() - t0) * 1000)
    finally:
        db.close()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    question = " ".join(sys.argv[1:]) or "what do we know?"
    facts = recall(question)
    print(f"{len(facts.triples)} facts in {facts.ms:.0f} ms")
    print(facts.as_text())
