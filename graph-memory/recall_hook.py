"""UserPromptSubmit hook: your notes, read before Claude answers.

Claude Code hands this hook the prompt on stdin as JSON. It runs the same two
legs as search.py and hands the top hits back as additionalContext.

It never blocks a prompt. No index, no prompt, no hits, or any failure at all,
and it prints nothing and exits 0.
"""

import json
import os
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from paths import DB  # noqa: E402
TOP = 5
BUDGET = 1500  # characters of context in total
PER_HIT = 280  # characters of chunk text per hit
READ_TIMEOUT = 0.25  # seconds; a prompt must never wait on the indexer
WORD_SNAP = 40  # how far the window may slide to avoid cutting a word
GRAPH_BUDGET = 600  # characters of graph-triples context in total

# ponytail: cosine floor on the meaning leg (BGE-small, unit-normalized vectors).
# Calibrated 2026-09-24 against 15 real prompts named from vault page titles
# (projects, systems, people) scoring
# 0.671-0.861, vs. ~20 nonsense/generic-coding prompts ("xyzzy plugh qwerty
# nonsense zzz", "what is 2+2", "rename this variable") scoring mostly
# 0.55-0.66 with a few coding-adjacent outliers up to ~0.72 (they coincidentally
# share vocabulary with a real wiki page — no scalar threshold separates those
# perfectly). 0.68 drops the nonsense case named in the audit and the bulk of
# generic junk while keeping 14/15 real prompts. Recalibrate if [index]
# embedding_model changes: other models spread cosine scores differently.
MEANING_THRESHOLD = 0.68


def hits(query):
    """The top rows for a query, as (label, one-line text) pairs.

    When the meaning leg is available, a candidate must clear
    MEANING_THRESHOLD on cosine similarity to be kept — this is what drops a
    nonsense prompt's stray keyword-only match (see MEANING_THRESHOLD). With
    no meaning leg (fastembed missing), there's no cosine to gate on, so
    keyword hits pass through as before.
    """
    from search import fuse, keyword_leg, meaning_leg

    db = sqlite3.connect(DB, timeout=READ_TIMEOUT)
    try:
        legs = {"keyword": keyword_leg(db, query)}
        scores = {}
        meaning = meaning_leg(db, query, scores=scores)
        if meaning is not None:
            legs["meaning"] = meaning
        ranked, _ = fuse(legs)
        out = []
        for rowid in ranked:
            if meaning is not None and scores.get(rowid, 0.0) < MEANING_THRESHOLD:
                continue
            file, section, text = db.execute(
                "SELECT file, section, text FROM chunks WHERE id=?", (rowid,)
            ).fetchone()
            out.append((f"[{file} § {section}]", " ".join(text.split())))
            if len(out) == TOP:
                break
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
    """Multi-hop typed triples for entities named in the prompt. Empty on any failure.

    `mentions` edges are dropped: they duplicate the text index (every
    wikilink is already in context) and judged 2% helpful in the sample that
    motivated typed edges (see docs/plans/2026-09-12-typed-wiki-graph.md).
    """
    try:
        from graph_recall import recall

        return recall(prompt, skip=("mentions",)).triples
    except Exception:
        return []


def graph_block(facts):
    """Facts trimmed to GRAPH_BUDGET. Whole triples only, never a half one.

    graph_facts already only returns anything when the prompt named an
    entity in the graph (graph_recall._seeds requires a name match), so no
    extra gate is needed here beyond the character cap.
    """
    lines, used = [], 0
    for s, p, t, doc in facts:
        line = f"{s} -[{p}]-> {t}  ({doc})"
        if lines and used + len(line) > GRAPH_BUDGET:
            break
        lines.append(line)
        used += len(line) + 1
    return lines


def main():
    if os.environ.get("MEMORY_STARTER_CHILD"):  # headless child of our own pipeline; nobody reads it
        return
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
    graph_lines = graph_block(facts) if facts else []
    if graph_lines:
        parts.append("Wiki graph:\n" + "\n".join(graph_lines))
    count = len(kept)
    label = f"memory: {count} hit{'' if count == 1 else 's'}"
    if graph_lines:
        label += f", {len(graph_lines)} graph facts"
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
