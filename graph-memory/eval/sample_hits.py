"""Sample real prompts from Claude Code transcripts, run the recall hook's
memory and graph legs on each, dump (prompt, position, score, legs, excerpt) rows."""
import csv, glob, json, os, random, re, sqlite3, sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from search import fuse, keyword_leg, meaning_leg, query_terms
from recall_hook import DB, excerpt
from graph_recall import recall, _seeds

N, TOPN, DAYS = 100, 10, 21
random.seed(7)
since = datetime.now() - timedelta(days=DAYS)

prompts = []
for f in glob.glob(os.path.expanduser("~/.claude/projects/*/*.jsonl")):
    if datetime.fromtimestamp(os.path.getmtime(f)) < since:
        continue
    with open(f, errors="ignore") as fh:
        for line in fh:
            try:
                d = json.loads(line)
            except Exception:
                continue
            if d.get("type") != "user" or d.get("isMeta") or d.get("isSidechain"):
                continue
            c = d.get("message", {}).get("content")
            if isinstance(c, list):
                c = " ".join(x.get("text", "") for x in c if x.get("type") == "text")
            if not isinstance(c, str):
                continue
            c = c.strip()
            if not c or c.startswith(("<", "[Image", "/")) or "tool_result" in c[:30]:
                continue
            prompts.append(c)

prompts = list(dict.fromkeys(prompts))
import os.path
if os.path.exists("prompts_fixed.json"):
    sample = json.load(open("prompts_fixed.json"))
    print("using frozen prompts", len(sample), file=sys.stderr)
else:
    sample = None
short = [p for p in prompts if len(p.split()) < 6]
long_ = [p for p in prompts if len(p.split()) >= 6]
if sample is None:
    sample = random.sample(short, min(N // 3, len(short))) + random.sample(long_, min(N - N // 3, len(long_)))
print(f"{len(prompts)} unique prompts, {len(short)} short; sampled {len(sample)}", file=sys.stderr)

db = sqlite3.connect(DB)
out = csv.writer(open(sys.argv[1] if len(sys.argv) > 1 else "hits.csv", "w", newline=""))
out.writerow(["prompt_id", "prompt", "n_words", "graph_seeds", "leg_type", "pos", "score", "legs", "label", "excerpt"])
for i, p in enumerate(sample):
    terms = query_terms(p)
    legs = {"keyword": keyword_leg(db, p)}
    m = meaning_leg(db, p)
    if m is not None:
        legs["meaning"] = m
    seeds = _seeds(db, p)
    ranked, found_by = fuse(legs)
    scores = {}
    for name, ids in legs.items():
        for rank, rid in enumerate(ids):
            scores[rid] = scores.get(rid, 0.0) + 1.0 / (60 + rank)
    for pos, rid in enumerate(ranked[:TOPN], 1):
        file, section, text = db.execute("SELECT file, section, text FROM chunks WHERE id=?", (rid,)).fetchone()
        out.writerow([i, p[:300], len(p.split()), len(seeds), "memory", pos, f"{scores[rid]:.5f}",
                      "+".join(found_by[rid]), f"{file} § {section}", excerpt(" ".join(text.split()), terms)])
    typed = recall(p, top_k=20, skip=("mentions",)).triples
    for pos, (s, pr, t, doc) in enumerate(typed, 1):
        out.writerow([i, p[:300], len(p.split()), len(seeds), "graph", pos, "", "", doc, f"{s} -[{pr}]-> {t}"])
