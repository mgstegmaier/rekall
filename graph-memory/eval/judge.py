"""Label sampled hits with a headless Claude judge.
Usage: python judge.py hits.csv outdir            -> one JSON per prompt in outdir
       python judge.py --score hits.csv out1 [out2 ...]  -> precision per row, averaged over label dirs
Run sample_hits.py first (it freezes prompts to prompts_fixed.json so runs compare)."""
import collections, csv, glob, json, os, re, subprocess, sys
from concurrent.futures import ThreadPoolExecutor

WORKERS = 8  # claude -p calls in flight at once

ASK = ("A hook injects note excerpts into an AI assistant's context when a user sends a prompt. "
       "Judge each item: would this excerpt plausibly help the assistant answer THIS prompt better than having nothing? "
       "Relevant means it is about the same specific subject the prompt is about (same project, person, system, or task). "
       "Sharing a common English word is NOT relevant. If the prompt is too vague to be about anything ('go', 'more!', 'merge'), nothing is relevant.\n\n"
       "PROMPT: {prompt}\n\nITEMS:\n{items}\n\nReply with ONLY a JSON object mapping each item id to true or false. No prose.")


def by_prompt(path):
    rows = collections.defaultdict(list)
    for r in csv.DictReader(open(path)):
        rows[r["prompt_id"]].append(r)
    return rows


def label(path, out):
    os.makedirs(out, exist_ok=True)

    def one(pid, v):
        if os.path.exists(f"{out}/{pid}.json"):
            return
        items = [f"{'M' if r['leg_type'] == 'memory' else 'G'}{r['pos']}: [{r['label']}] {r['excerpt'][:300]}" for r in v]
        res = subprocess.run(["claude", "-p", "--model", "haiku", "--permission-mode", "bypassPermissions", "--output-format", "text"],
                             input=ASK.format(prompt=v[0]["prompt"], items="\n".join(items)), capture_output=True, text=True)
        open(f"{out}/{pid}.json", "w").write(res.stdout)

    with ThreadPoolExecutor(WORKERS) as pool:
        list(pool.map(lambda kv: one(*kv), by_prompt(path).items()))


def labels(out):
    lab = {}
    for f in glob.glob(f"{out}/*.json"):
        m = re.search(r"\{.*\}", open(f).read(), re.S)
        if m:
            lab[os.path.basename(f)[:-5]] = json.loads(m.group())
    return lab


def score(path, outs):
    """Precision by row, averaged over one or more label dirs (judge the same hits
    twice and pass both dirs: the judge's own noise is about 5 points per run)."""
    labs = [labels(o) for o in outs]
    rows = [r for v in by_prompt(path).values() for r in v]
    for r in rows:
        key = ("M" if r["leg_type"] == "memory" else "G") + r["pos"]
        votes = [lab.get(r["prompt_id"], {}).get(key) for lab in labs]
        votes = [v for v in votes if v is not None]
        r["rel"] = sum(votes) / len(votes) if votes else None
    rows = [r for r in rows if r["rel"] is not None]

    def prec(rs):
        return f"{sum(r['rel'] for r in rs) / max(len(rs), 1):.3f} (n={len(rs)})"
    mem = [r for r in rows if r["leg_type"] == "memory"]
    print("memory  top4:", prec([r for r in mem if int(r["pos"]) <= 4]),
          " pos1:", prec([r for r in mem if int(r["pos"]) == 1]),
          " keyword-only:", prec([r for r in mem if r["legs"] == "keyword"]),
          " meaning-only:", prec([r for r in mem if r["legs"] == "meaning"]),
          " both:", prec([r for r in mem if r["legs"] == "keyword+meaning"]))
    gr = [r for r in rows if r["leg_type"] == "graph"]
    if gr:
        print("graph hook slice (pos 1-8):", prec([r for r in gr if int(r["pos"]) <= 8]))


if __name__ == "__main__":
    if sys.argv[1] == "--score":
        score(sys.argv[2], sys.argv[3:])
    else:
        label(sys.argv[1], sys.argv[2])
