#!/usr/bin/env python3
"""Granola -> vault -> wiki sweep. Optional companion to fathom-pipeline.py.

Plan: vault wiki/plans/2026-09-15-granola-sweep.md.

Each run:
1. List Granola notes created since the window start, fetch each new one, keep those the user
   (WORK_EMAIL) attended and whose meeting ended more than LAG_HOURS ago (Fathom's note has landed).
2. Match against Fathom notes already in meetings/: same date, start within 30 minutes, at least
   half the attendee names in common. Title similarity is only a tiebreaker.
3. Match: APPEND one "## Granola notes" section to the Fathom note, once. Nothing above it changes.
   No match: write a new meeting note in the Fathom pipeline's layout with source: granola.
4. Digest line in today.md, wiki ingest through the pipeline's ingest_to_wiki.
5. State in ~/.config/rekall/granola-state.json, own lock. No Monday push.

No GRANOLA_API_KEY: one log line, exit 0. The key is the on/off switch.
Flags: --hours N (default 26) | --since YYYY-MM-DD | --no-wiki | --dry-run

API shape (Granola OpenAPI, docs.granola.ai/api-reference): GET /v1/notes pages with `cursor`
and `hasMore` and returns summaries only (id, title, created_at, updated_at, owner). GET
/v1/notes/{id} adds attendees[{name,email}], calendar_event{scheduled_start_time,
scheduled_end_time, event_title}, summary_markdown, web_url.
"""
import argparse
import difflib
import importlib.util
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

_spec = importlib.util.spec_from_file_location("fathom_pipeline", Path(__file__).parent / "fathom-pipeline.py")
fp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fp)

GRANOLA_BASE = "https://public-api.granola.ai/v1"
STATE_FILE = fp.STATE_DIR / "granola-state.json"
LOCK_FILE = fp.STATE_DIR / "granola-sweep.lock"
LAG_HOURS = 2       # ponytail: fixed lag instead of cross-script coordination; tighten if Fathom's latency matters
MATCH_WINDOW_MIN = 30
SECTION = "## Granola notes"
log = fp.log


# ── Fetch ───────────────────────────────────────────────────

def _iso(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def fetch_notes(created_after, known_ids):
    """Granola notes the user attended, in the pipeline's meeting dict shape, plus `end`."""
    key = fp.env("GRANOLA_API_KEY")
    headers = {"Authorization": f"Bearer {key}"}
    user_email = (fp.env("WORK_EMAIL", "JIRA_EMAIL") or "").lower()
    params = urlencode({"created_after": created_after.strftime("%Y-%m-%dT%H:%M:%SZ"), "page_size": 30})
    summaries, cursor = [], None
    while True:
        data = fp.http_json(f"{GRANOLA_BASE}/notes?{params}" + (f"&cursor={cursor}" if cursor else ""), headers)
        summaries += data.get("notes") or []
        cursor = data.get("cursor")
        if not data.get("hasMore") or not cursor:
            break

    meetings = []
    for s in summaries:
        if s["id"] in known_ids:
            continue
        n = fp.http_json(f"{GRANOLA_BASE}/notes/{s['id']}", headers)
        attendees = n.get("attendees") or []
        emails = {(a.get("email") or "").lower() for a in attendees} | {((n.get("owner") or {}).get("email") or "").lower()}
        if user_email and user_email not in emails:
            continue
        cal = n.get("calendar_event") or {}
        start = _iso(cal.get("scheduled_start_time")) or _iso(n["created_at"])
        end = _iso(cal.get("scheduled_end_time")) or start + timedelta(hours=1)
        duration = int((end - start).total_seconds() / 60)
        meetings.append({
            "id": n["id"],
            "title": n.get("title") or cal.get("event_title") or "(untitled meeting)",
            "dt": start.astimezone(fp.CT),
            "end": end,
            "duration": duration if 0 < duration < 480 else None,
            "participants": [a.get("name") or a.get("email", "Unknown") for a in attendees],
            "summary": n.get("summary_markdown") or "",
            "action_items": [],
            "url": n.get("web_url") or "",
        })
    meetings.sort(key=lambda m: m["dt"])
    return meetings


# ── Match ───────────────────────────────────────────────────

def parse_note(path):
    """(start datetime in CT or None, set of lowercased attendee names, title, is_granola)."""
    text = path.read_text(errors="ignore")
    fm = text.split("---", 2)[1] if text.startswith("---") else ""
    att = re.search(r"^attendees:\n((?:[ \t]+-[^\n]*\n)+)", fm, re.M)
    names = {l.strip()[1:].strip().strip('"\'').lower() for l in att.group(1).splitlines()} if att else set()
    title_m = re.search(r"^title:\s*(.+)$", fm, re.M)
    title = title_m.group(1).strip().strip('"\'') if title_m else path.stem
    is_granola = bool(re.search(r"^source:\s*granola", fm, re.M))
    when = re.search(r"^\*\*Date:\*\*\s*(\d{4}-\d{2}-\d{2})(?:\s+at\s+(\d{1,2}:\d{2}\s*[AP]M))?", text, re.M)
    start = None
    if when and when.group(2):
        start = datetime.strptime(f"{when.group(1)} {when.group(2)}", "%Y-%m-%d %I:%M %p").replace(tzinfo=fp.CT)
    return start, names, title, is_granola


def find_fathom_match(m, meetings_dir=None):
    """Path of the Fathom note for the same meeting, or None."""
    meetings_dir = meetings_dir or fp.MEETINGS
    date_str = m["dt"].strftime("%Y-%m-%d")
    mine = {p.lower() for p in m["participants"]}
    best = []
    for path in sorted(meetings_dir.glob(f"{date_str}-*.md")):
        start, names, title, is_granola = parse_note(path)
        if is_granola or start is None or not names or not mine:
            continue
        if abs((start - m["dt"]).total_seconds()) > MATCH_WINDOW_MIN * 60:
            continue
        overlap = len(mine & names) / min(len(mine), len(names))
        if overlap < 0.5:
            continue
        sim = difflib.SequenceMatcher(None, title.lower(), m["title"].lower()).ratio()
        best.append((overlap, sim, path))
    return max(best)[2] if best else None


def append_granola_section(path, m, now=None):
    """Append the section once. Returns True if written, False if already present."""
    text = path.read_text()
    if SECTION in text:
        return False
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    link = f"[Granola]({m['url']})" if m["url"] else "none"
    block = (f"\n{SECTION}\n\n**Source:** granola `{m['id']}` · **Transcript:** {link} · appended {stamp}\n\n"
             f"{m['summary'] or '_No summary from Granola._'}\n")
    path.write_text(text.rstrip("\n") + "\n" + block)
    return True


def write_granola_note(m):
    """New note in the pipeline's layout, tagged source: granola. Returns relative path or None if it exists."""
    rel = fp.write_note(m)
    if rel is None:
        return None
    path = fp.VAULT / rel
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    path.write_text(path.read_text().replace(
        "status: active\n", f"status: active\nsource: granola\ngenerated: {{by: granola-sweep, at: {stamp}}}\n", 1))
    return rel


# ── State ───────────────────────────────────────────────────

def load_state():
    return json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {"notes": {}}


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


# ── Main ────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=int, default=26)
    ap.add_argument("--since", help="backfill start date YYYY-MM-DD")
    ap.add_argument("--no-wiki", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not fp.env("GRANOLA_API_KEY"):
        log("no GRANOLA_API_KEY set; Granola sweep is off")
        return

    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    if fp.acquire_lock(LOCK_FILE) is None:  # held until exit, same as the pipeline
        log("another Granola sweep is active; exiting")
        return

    now = datetime.now(timezone.utc)
    start = (datetime.strptime(args.since, "%Y-%m-%d").replace(tzinfo=timezone.utc) if args.since
             else now - timedelta(hours=args.hours))
    state = load_state()
    try:
        meetings = fetch_notes(start, set(state["notes"]))
    except fp.urllib.error.HTTPError as e:
        body = e.read().decode(errors="ignore")[:200]
        fp.notify(f"Granola API refused the sweep: HTTP {e.code} {body}", title="Granola sweep")
        sys.exit(1)
    ready = [m for m in meetings if m["end"] <= now - timedelta(hours=LAG_HOURS)]
    log(f"{len(meetings)} new Granola notes in window, {len(ready)} past the {LAG_HOURS}h lag")

    if args.dry_run:
        for m in ready:
            match = find_fathom_match(m)
            day = m["dt"].strftime("%Y-%m-%d")
            if match:
                state_word = "already appended" if SECTION in match.read_text() else "would append to"
                log(f"  {day} {m['title']}: {state_word} {match.name}")
            elif (fp.MEETINGS / f"{day}-{fp.slugify(m['title'])}.md").exists():
                log(f"  {day} {m['title']}: note exists")
            else:
                log(f"  {day} {m['title']}: would write new note")
        return

    fp.rollover_today_note()
    digest = []
    for m in ready:
        match = find_fathom_match(m)
        show_digest = True
        if match:
            note_rel = str(match.relative_to(fp.VAULT))
            appended = append_granola_section(match, m)
            log(f"  {'appended Granola section to' if appended else 'Granola section already present:'} {note_rel}")
            # already present means an earlier run ingested it; don't pay for a second session
            entry = {"note": note_rel, "merged_into": note_rel, "ingested": not appended}
            label = " (merged into Fathom note)"
        else:
            note_rel = write_granola_note(m)
            if note_rel is None:
                note_rel = f"wiki/meetings/{m['dt'].strftime('%Y-%m-%d')}-{fp.slugify(m['title'])}.md"
                log(f"  note exists, skipping write: {note_rel}")
                entry = {"note": note_rel, "merged_into": None, "ingested": True}  # hand-pasted note, already in the wiki
                show_digest = False
            else:
                log(f"  wrote {note_rel}")
                entry = {"note": note_rel, "merged_into": None, "ingested": False}
            label = " (Granola)"
        if show_digest:
            digest.append(fp.digest_entry({**m, "title": m["title"] + label}, note_rel, False))
        state["notes"][m["id"]] = entry
        save_state(state)
    fp.append_digest(digest)

    if args.no_wiki:
        return
    failures = state.setdefault("ingest_failures", {})
    pending = [e["note"] for e in state["notes"].values() if not e["ingested"] and failures.get(e["note"], 0) < 2]
    log(f"wiki ingest: {len(pending)} pending sources")
    for i in range(0, len(pending), fp.INGEST_BATCH):
        batch = pending[i:i + fp.INGEST_BATCH]
        ok = fp.ingest_to_wiki(batch, extra="Some sources are Fathom notes with a newly appended '## Granola notes' "
                                           "section; only that section is new to the wiki.")
        for s in batch:
            if ok:
                failures.pop(s, None)
                for e in state["notes"].values():
                    if e["note"] == s:
                        e["ingested"] = True
            else:
                failures[s] = failures.get(s, 0) + 1  # ponytail: quarantined at 2, no per-source retry
        save_state(state)
        if not ok:
            fp.notify("Granola sweep: wiki ingest failed for a batch; stopping this run", title="Granola sweep")
            break
    if any(e["ingested"] for e in state["notes"].values()):
        import subprocess
        regen = subprocess.run([sys.executable, str(Path(__file__).parent / "wiki-index.py")],
                               capture_output=True, text=True, timeout=120)
        log(f"  index regen: exit {regen.returncode} ({regen.stdout.strip() or regen.stderr.strip()})")


if __name__ == "__main__":
    main()
