"""Pre-merge recall gate: hand-written prompts with the page and section each should find.

Runs every prompt in gate_prompts.json through recall_hook.hits (the hook's own search path),
prints recall@4 (the share of prompts whose expected file and section is in the top 4), and
exits 1 when it falls 2 points or more below gate_baseline.json. Deterministic, no judge.

    python eval/gate.py                    # compare against the baseline
    python eval/gate.py --write-baseline   # accept the current number
"""

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from recall_hook import DB, hits  # noqa: E402

PROMPTS = HERE / "gate_prompts.json"
BASELINE = HERE / "gate_baseline.json"
DROP = 0.02  # two points
LABEL = re.compile(r"^\[(.*) § (.*)\]$")


def found(case):
    """True when the expected file and section sit in the hook's top 4 for this prompt."""
    for label, _ in hits(case["prompt"])[:4]:
        file, section = LABEL.match(label).groups()
        if file == case["expect_file"] and case["expect_section_substring"].lower() in section.lower():
            return True
    return False


def main():
    if not DB.is_file():
        sys.exit(f"no index at {DB}: run graph-memory/reindex.sh first")
    cases = json.loads(PROMPTS.read_text(encoding="utf-8"))
    misses = [c["prompt"] for c in cases if not found(c)]
    recall = round(1 - len(misses) / len(cases), 3)
    for prompt in misses:
        print(f"  miss: {prompt}")
    print(f"recall@4 {recall:.3f} ({len(cases) - len(misses)}/{len(cases)})")
    if "--write-baseline" in sys.argv:
        BASELINE.write_text(json.dumps({"recall_at_4": recall, "n": len(cases)}) + "\n", encoding="utf-8")
        print(f"baseline written: {BASELINE.name}")
        return
    base = json.loads(BASELINE.read_text(encoding="utf-8"))["recall_at_4"]
    print(f"baseline {base:.3f}")
    if recall <= base - DROP + 1e-9:
        sys.exit(f"FAIL: recall@4 dropped {base - recall:.3f} (gate is {DROP})")
    print("pass")


if __name__ == "__main__":
    main()
