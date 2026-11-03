"""Graded recall gate: real prompts whose candidate sections a judge has already graded.

Each case in <data>/eval/judged_prompts.json is {"q", "date", "grades": {"file § section": 0|1|2}}:
2 is directly relevant, 1 related background, 0 not useful. The file lives beside rag.db,
not in the repo, because real prompts carry names and work details. Every prompt runs
through the hook's own main(), minus session digests and meetings dated on or after the
prompt (see as_of), and the gate scores the sections the hook would show:

    useful       prompts that have a grade-2 section, where the hook shows one
    junk         shown sections graded 0, per prompt
    silent-ok    prompts with no grade-2 section, where the hook shows nothing
    unjudged     shown sections with no grade yet (a change surfaced them, or a newer page did)

It exits 1 when useful falls 2 points or more below <data>/eval/judged_baseline.json.
Junk and silence are printed against the baseline but don't fail it. Unjudged sections
count as neither useful nor junk; when they pass 20 percent of what's shown, grade them
(--unjudged lists them; add each to its case's "grades") before trusting the number.

    python eval/judged_gate.py                    # compare against the baseline
    python eval/judged_gate.py --write-baseline   # accept the current numbers
    python eval/judged_gate.py --unjudged         # list shown sections that need a grade
"""

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import recall_hook  # noqa: E402
from hook_output import emit, items  # noqa: E402
from paths import DATA  # noqa: E402
from recall_hook import DB  # noqa: E402

CASES = DATA / "eval" / "judged_prompts.json"
BASELINE = DATA / "eval" / "judged_baseline.json"
DROP = 0.02  # two points, as in gate.py
UNJUDGED_WARN = 0.20
LABEL = re.compile(r"^\[(.*)\]$")
DATED = re.compile(r"^(sessions|meetings)/(\d{4}-\d{2}-\d{2})")


def as_of(query, day):
    """The sections the hook would show for query, as the prompt's day saw them.

    Runs the hook's own main() (hook_output.emit), so its early returns and its
    1,500-character budget decide what's shown, usually 4 sections of the 5 hits.
    Session digests and meetings dated on or after day didn't exist yet and often
    describe the prompt's own session, so they're dropped inside hits() and the next
    gated section takes the slot. Recency still counts from today.
    """
    real = recall_hook.hits

    def dated_hits(q, *a, **kw):
        top, recall_hook.TOP = recall_hook.TOP, 100  # the whole gated list; the legs cap it near 20
        try:
            found = real(q, *a, **kw)
        finally:
            recall_hook.TOP = top
        return [h for h in found if not ((m := DATED.match(LABEL.match(h[0]).group(1))) and m.group(2) >= day)][:top]

    recall_hook.hits = dated_hits  # main() looks hits up at call time; emit() wraps whatever is here
    try:
        return [label for kind, label, *_ in items(emit(query)) if kind == "memory"]
    finally:
        recall_hook.hits = real


def score(cases, search=as_of):
    """The four counts over cases, plus the unjudged (prompt, section) pairs."""
    useful = junk = silent = shown = 0
    unjudged = []
    needs = [c for c in cases if 2 in c["grades"].values()]
    for c in cases:
        keys = search(c["q"], c["date"])
        grades = [c["grades"].get(k) for k in keys]
        useful += 2 in grades
        junk += grades.count(0)
        silent += not keys and 2 not in c["grades"].values()
        shown += len(keys)
        unjudged += [(c["q"], k) for k, g in zip(keys, grades) if g is None]
    n = len(cases)
    return {
        "useful": round(useful / max(len(needs), 1), 3),
        "junk_per_prompt": round(junk / max(n, 1), 3),
        "silent_ok": round(silent / max(n - len(needs), 1), 3),
        "unjudged_share": round(len(unjudged) / max(shown, 1), 3),
        "n": n,
        "needs": len(needs),
    }, unjudged


def main():
    if not DB.is_file():
        sys.exit(f"no index at {DB}: run graph-memory/reindex.sh first")
    if not CASES.is_file():
        sys.exit(f"no judged prompts at {CASES}: this gate needs a graded set of your own prompts")
    cases = json.loads(CASES.read_text(encoding="utf-8"))
    got, unjudged = score(cases, as_of)
    if "--unjudged" in sys.argv:
        for q, key in unjudged:
            print(f"{key}\n    for: {q[:120]!r}")
        return
    print(f"useful {got['useful']:.3f} of {got['needs']} prompts; junk {got['junk_per_prompt']:.2f} per prompt; "
          f"silent-ok {got['silent_ok']:.3f} of {got['n'] - got['needs']}; unjudged {got['unjudged_share']:.0%} of shown")
    if got["unjudged_share"] > UNJUDGED_WARN:
        print(f"warning: {got['unjudged_share']:.0%} of shown sections are unjudged; grade them (--unjudged) before trusting this")
    if "--write-baseline" in sys.argv:
        BASELINE.write_text(json.dumps(got) + "\n", encoding="utf-8")
        print(f"baseline written: {BASELINE}")
        return
    if not BASELINE.is_file():
        sys.exit(f"no baseline at {BASELINE}: run with --write-baseline first")
    base = json.loads(BASELINE.read_text(encoding="utf-8"))
    print(f"baseline useful {base['useful']:.3f}; junk {base['junk_per_prompt']:.2f}; silent-ok {base['silent_ok']:.3f}")
    if got["useful"] <= base["useful"] - DROP + 1e-9:
        sys.exit(f"FAIL: useful dropped {base['useful'] - got['useful']:.3f} (gate is {DROP})")
    print("pass")


if __name__ == "__main__":
    main()
