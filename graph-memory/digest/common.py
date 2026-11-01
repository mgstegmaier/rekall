"""What the three digest scripts all need: the config, your notes, the log."""

import json
import re
import sqlite3
from datetime import datetime
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))  # flat vendored layout, no rag/ subdir

from paths import DB as RAG_DB, DIGEST_LOG as LOG, DIGEST_PENDING as PENDING  # noqa: E402

CONFIG = HERE / "config.json"
PROMPT = HERE / "digest-prompt.md"
NEW_MARKER = "[--- new since the last write-up ---]"  # session_end puts it in, headless_run reads it

DEFAULTS = {
    "mode": "session",
    "min_turns": 5,
    "max_chars": 40000,
    "model": "sonnet",
    "log_dir": "daily",
    "distil": True,
}


def config():
    """config.json over the defaults. A broken file never stops the digest."""
    cfg = dict(DEFAULTS)
    try:
        loaded = json.loads(CONFIG.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            cfg.update(loaded)
    except Exception:
        pass
    return cfg


def corpus():
    """Your notes folder, as build_index recorded it. None when there is no index."""
    if not RAG_DB.is_file():
        return None
    try:
        db = sqlite3.connect(RAG_DB)
        row = db.execute("SELECT value FROM meta WHERE key='corpus'").fetchone()
        db.close()
    except Exception:
        return None
    if not row or not row[0]:
        return None
    path = Path(row[0])
    return path if path.is_dir() else None


def today_log(notes, cfg, when=None):
    """Today's log file inside your notes. The folder is made if it is missing."""
    when = when or datetime.now()
    folder = Path(notes) / cfg["log_dir"]
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{when:%Y-%m-%d}.md"


def note_failure(name, message):
    """Write a failure where a member can find it, and never raise doing it."""
    try:
        LOG.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().isoformat(timespec="seconds")
        with (LOG / "digest.log").open("a", encoding="utf-8") as handle:
            handle.write(f"{stamp} {name}: {message}\n")
    except Exception:
        pass


HEX8 = re.compile(r"[0-9a-f]{8}")
RECORDED_SHARE = 4  # the already-recorded block gets at most 1/RECORDED_SHARE of max_chars


def section(text, name):
    """The body under `### name`, up to the next heading, or ''."""
    m = re.search(rf"^### {re.escape(name)}[ \t]*\n(.*?)(?=^#{{2,3}} |\Z)", text, re.M | re.S)
    return m[1].strip() if m else ""


def session_entries(folder, id8):
    """Every entry already written for this session, oldest first: (day, heading, body) for each
    `## Session HH:MM · <id8>` block in folder/*.md, running to the next `## ` line."""
    found = []
    head = re.compile(rf"^## (Session \d\d:\d\d · {re.escape(id8)})[ \t]*\n(.*?)(?=^## |\Z)", re.M | re.S)
    for day in sorted(Path(folder).glob("*.md")):
        found += [(day.stem, m[1], m[2].strip()) for m in head.finditer(day.read_text(encoding="utf-8"))]
    return found


def recorded(earlier, cap):
    """What the model is told is already recorded, at most cap chars (separator included), or ''
    when there is nothing or no room. Each older entry gives its Decisions and Open loops and the
    latest gives its whole body. Over cap, older entries shrink to one heading line each, then the
    latest to its Decisions and Open loops, then the older ones go and the latest is cut."""
    if not earlier or cap < 200:
        return ""
    sep = "\n\n---\n\n"

    def keep(body):
        return "\n".join(f"### {n}\n{section(body, n)}" for n in ("Decisions", "Open loops") if section(body, n))

    def build(older, latest_body):
        d, h, _ = earlier[-1]
        blocks = older + [f"[{d} {h[8:13]}, latest entry]\n{latest_body}"]
        return "Already recorded for this session:\n\n" + "\n\n".join(blocks) + sep

    older = [(f"[{d} {h[8:13]}, earlier entry]", keep(b)) for d, h, b in earlier[:-1]]
    latest = earlier[-1][2]
    for blocks, body in (([f"{t}\n{k}" for t, k in older if k], latest),
                         ([t for t, _ in older], latest),
                         ([t for t, _ in older], keep(latest)),
                         ([], keep(latest))):
        out = build(blocks, body)
        if len(out) <= cap:
            return out
    return out[: cap - len(sep) - 6] + " [...]" + sep
