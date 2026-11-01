"""Sample real prompts from Claude Code transcripts, run each through the recall hook
itself, and dump one row per item the hook injected (prompt, position, legs, excerpt,
graph predicate). A prompt the hook stays silent on yields no rows.

    python sample_hits.py hits.csv            # sample (or reuse prompts_fixed.json)
    python sample_hits.py hits.csv --freeze   # also write the sample to prompts_fixed.json
"""
import csv, glob, json, os, random, sys
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
from hook_output import emit, items

N, DAYS = int(os.environ.get("EVAL_N", 100)), int(os.environ.get("EVAL_DAYS", 21))
COLUMNS = ["prompt_id", "prompt", "n_words", "graph_seeds", "leg_type", "pos", "score", "legs", "label", "excerpt", "pred"]


def transcript_prompts(days=DAYS):
    since = datetime.now() - timedelta(days=days)
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
    return list(dict.fromkeys(prompts))


def draw(prompts, n=N):
    random.seed(7)
    short = [p for p in prompts if len(p.split()) < 6]
    long_ = [p for p in prompts if len(p.split()) >= 6]
    print(f"{len(prompts)} unique prompts, {len(short)} short", file=sys.stderr)
    return random.sample(short, min(n // 3, len(short))) + random.sample(long_, min(n - n // 3, len(long_)))


def freeze(sample, path):
    Path(path).write_text(json.dumps(sample, indent=1) + "\n", encoding="utf-8")


def hook_rows(i, prompt, output, legs_by_label, seeds=0):
    """Row dicts for what the hook emitted. `legs_by_label` maps "file § section" to the
    legs that found it ("keyword+meaning"); the hook's output doesn't say."""
    rows, pos = [], {"memory": 0, "graph": 0}
    for kind, label, excerpt, pred in items(output):
        pos[kind] += 1
        rows.append({"prompt_id": i, "prompt": prompt[:300], "n_words": len(prompt.split()), "graph_seeds": seeds,
                     "leg_type": kind, "pos": pos[kind], "score": "",
                     "legs": legs_by_label.get(label, "") if kind == "memory" else "",
                     "label": label, "excerpt": excerpt, "pred": pred})
    return rows


def legs_by_label(db, prompt):
    from search import fuse, keyword_leg, meaning_leg

    legs = {"keyword": keyword_leg(db, prompt)}
    m = meaning_leg(db, prompt)
    if m is not None:
        legs["meaning"] = m
    # EVAL_NO_RECENCY=1 ranks the way the hook did before recency weighting, for an A/B
    ranked, found_by = fuse(legs, None if os.environ.get("EVAL_NO_RECENCY") else db)
    labels = {}
    for rid in ranked:
        file, section = db.execute("SELECT file, section FROM chunks WHERE id=?", (rid,)).fetchone()
        labels[f"{file} § {section}"] = "+".join(found_by[rid])
    return labels


def main(argv):
    import sqlite3
    from graph_recall import _seeds
    from recall_hook import DB

    args = [a for a in argv[1:] if a != "--freeze"]
    frozen = Path(os.environ.get("EVAL_PROMPTS", HERE / "prompts_fixed.json"))
    if "--freeze" in argv or not frozen.exists():
        sample = draw(transcript_prompts())
        if "--freeze" in argv:
            freeze(sample, frozen)
            print(f"froze {len(sample)} prompts to {frozen}", file=sys.stderr)
    else:
        sample = json.loads(frozen.read_text(encoding="utf-8"))
        print("using frozen prompts", len(sample), file=sys.stderr)

    db = sqlite3.connect(DB)
    silent = 0
    with open(args[0] if args else "hits.csv", "w", newline="") as fh:
        out = csv.DictWriter(fh, COLUMNS)
        out.writeheader()
        for i, p in enumerate(sample):
            output = emit(p)
            rows = hook_rows(i, p, output, legs_by_label(db, p) if output else {}, len(_seeds(db, p)) if output else 0)
            silent += not rows
            out.writerows(rows)
    print(f"{len(sample)} prompts, hook silent on {silent}", file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv)
