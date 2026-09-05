"""UserPromptSubmit hook: your notes, read before Claude answers.

Claude Code hands this hook the prompt on stdin as JSON. It runs the same two
legs as search.py and hands the top hits back as additionalContext.

It never blocks a prompt. No index, no prompt, no hits, or any failure at all,
and it prints nothing and exits 0.
"""

import json
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from paths import DB  # noqa: E402
TOP = 5
BUDGET = 1500  # characters of context in total
PER_HIT = 280  # characters of chunk text per hit
WORD_SNAP = 40  # how far the window may slide to avoid cutting a word


def hits(query):
    """The top rows for a query, as (label, one-line text) pairs."""
    from search import fuse, keyword_leg, meaning_leg

    db = sqlite3.connect(DB)
    try:
        legs = {"keyword": keyword_leg(db, query)}
        meaning = meaning_leg(db, query)
        if meaning is not None:
            legs["meaning"] = meaning
        ranked, _ = fuse(legs)
        out = []
        for rowid in ranked[:TOP]:
            file, section, text = db.execute(
                "SELECT file, section, text FROM chunks WHERE id=?", (rowid,)
            ).fetchone()
            out.append((f"[{file} § {section}]", " ".join(text.split())))
        return out
    finally:
        db.close()


def excerpt(text, terms):
    """PER_HIT characters of text, centred on the query terms, not the head.

    A long section usually matches on a sentence well past its first PER_HIT
    characters, and the head then shows Claude everything except the answer.
    With no term to anchor on (a meaning-leg-only hit) this is the head, as
    before.
    """
    if len(text) <= PER_HIT:
        return text
    low = text.lower()
    spots = [low.index(t) for t in terms if t in low]
    if not spots:
        return text[:PER_HIT] + "..."
    # of the windows anchored on each match, the one covering the most terms
    start = max(
        (max(0, spot - PER_HIT // 4) for spot in spots),
        key=lambda s: sum(1 for t in terms if t in low[s : s + PER_HIT]),
    )
    end = min(len(text), start + PER_HIT)
    # snap to whole words; text arrives as one space-joined line
    if start:
        space = text.find(" ", start)
        if 0 <= space < start + WORD_SNAP:
            start = space + 1
    if end < len(text):
        space = text.rfind(" ", start, end)
        if space > start:
            end = space
    return ("..." if start else "") + text[start:end] + ("..." if end < len(text) else "")


def block(found, query):
    """The hits trimmed to the budget. Whole hits only, never a half one."""
    from search import query_terms

    terms = query_terms(query)
    kept, used = [], 0
    for label, text in found:
        entry = f"{label}\n{excerpt(text, terms)}"
        if kept and used + len(entry) > BUDGET:
            break
        kept.append(entry)
        used += len(entry) + 2
    return kept


def graph_facts(prompt):
    """Multi-hop triples for entities named in the prompt. Empty on any failure."""
    try:
        from graph_recall import recall

        return recall(prompt).triples
    except Exception:
        return []


def main():
    try:
        prompt = json.load(sys.stdin).get("prompt", "")
    except Exception:
        return
    if not isinstance(prompt, str) or not prompt.strip() or not DB.is_file():
        return
    try:
        kept = block(hits(prompt), prompt)
    except Exception:
        kept = []
    facts = graph_facts(prompt)
    if not kept and not facts:
        return
    parts = []
    if kept:
        parts.append("From your notes:\n\n" + "\n\n".join(kept))
    if facts:
        parts.append(
            "Wiki graph:\n" + "\n".join(f"{s} -[{p}]-> {t}  ({doc})" for s, p, t, doc in facts)
        )
    count = len(kept)
    label = f"memory: {count} hit{'' if count == 1 else 's'}"
    if facts:
        label += f", {len(facts)} graph facts"
    print(
        json.dumps(
            {
                "systemMessage": label,
                "hookSpecificOutput": {
                    "hookEventName": "UserPromptSubmit",
                    "additionalContext": "\n\n".join(parts),
                },
            }
        )
    )


if __name__ == "__main__":
    main()
    sys.exit(0)
