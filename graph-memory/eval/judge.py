"""Label sampled hits with a headless Claude judge.
Usage: python judge.py hits.csv outdir   -> one JSON per prompt in outdir
       python judge.py --score hits.csv outdir  -> precision by leg, position, predicate
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


def score(path, out):
    lab = {}
    for f in glob.glob(f"{out}/*.json"):
        m = re.search(r"\{.*\}", open(f).read(), re.S)
        if m:
            lab[os.path.basename(f)[:-5]] = json.loads(m.group())
    rows = [r for v in by_prompt(path).values() for r in v]
    for r in rows:
        r["rel"] = lab.get(r["prompt_id"], {}).get(("M" if r["leg_type"] == "memory" else "G") + r["pos"])
    rows = [r for r in rows if r["rel"] is not None]

    def prec(rs):
        return f"{sum(r['rel'] for r in rs)}/{len(rs)} = {sum(r['rel'] for r in rs) / max(len(rs), 1):.2f}"
    mem = [r for r in rows if r["leg_type"] == "memory"]
    gr = [r for r in rows if r["leg_type"] == "graph"]
    print("memory top4:", prec([r for r in mem if int(r["pos"]) <= 4]), " both-legs:", prec([r for r in mem if "+" in r["legs"]]))
    print("graph hook slice (pos 1-8):", prec([r for r in gr if int(r["pos"]) <= 8]))
    preds = collections.defaultdict(list)
    for r in gr:
        if int(r["pos"]) <= 8:
            preds[r["excerpt"].split("-[")[1].split("]")[0]].append(r)
    for p, rs in sorted(preds.items()):
        print(f"  {p:11} {prec(rs)}")


if __name__ == "__main__":
    if sys.argv[1] == "--score":
        score(sys.argv[2], sys.argv[3])
    else:
        label(sys.argv[1], sys.argv[2])
