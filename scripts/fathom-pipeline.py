#!/usr/bin/env python3
"""Fathom -> vault -> wiki -> Monday pipeline.

Plan: docs/plans/2026-08-21-wiki-revival-fathom-pipeline.md (Phase 2).

Each run:
1. Pull new completed Fathom meetings the user (WORK_EMAIL) attended (API details: connections/services/fathom.md)
2. Write one note per meeting to meetings/{YYYY-MM-DD}-{slug}.md (template: skills/today/references/workflow.md)
3. Push the user's action items to the [monday] group/board from rekall.toml, if MONDAY_API_TOKEN is set
4. Ingest new meeting notes + new raw/ files into the flat wiki via headless claude
5. Track processed meeting IDs in ~/.config/rekall/fathom-pipeline-state.json (idempotent)

Paths and settings: rekall.toml at the repo root. Secrets: .env at the repo root, or Doppler
(run-fathom-pipeline.sh picks whichever exists).
Flags: --hours N (default 26) | --since YYYY-MM-DD (backfill) | --no-monday | --no-wiki | --dry-run
"""

import argparse
import fcntl
import hashlib
import json
import re
import ssl
import subprocess
import threading
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rekall_config import MONDAY_BOARD, MONDAY_GROUP, STATE_DIR, TIMEZONE, VAULT  # noqa: E402

MEETINGS = VAULT / "wiki" / "meetings"
RAW = VAULT / "wiki" / "raw"
WIKI_LOG = VAULT / "wiki" / "log.md"
WIKI_TYPED_DIRS = ["people", "projects", "entities", "concepts", "summaries"]
STATE_FILE = STATE_DIR / "fathom-pipeline-state.json"
LOG_DIR = STATE_DIR / "logs"
LOCK_FILE = STATE_DIR / "fathom-pipeline.lock"
CT = ZoneInfo(TIMEZONE)
FATHOM_BASE = "https://api.fathom.ai/external/v1"
INGEST_BATCH = 5


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def notify(msg, title="Fathom pipeline"):
    """macOS notification; never raises. An unattended job must be able to say it's broken."""
    log(f"  NOTIFY: {msg}")
    try:
        subprocess.run(
            ["osascript", "-e", f"display notification {json.dumps(msg)} with title {json.dumps(title)}"],
            capture_output=True, timeout=10)
    except Exception:
        pass


def env(key, fallback=None):
    import os
    return os.environ.get(key) or (os.environ.get(fallback) if fallback else None)


# A corporate security proxy that re-signs TLS breaks urllib's verification; the combined
# bundle is certifi + the exported proxy CA. How to build it: SETUP.md, "Corporate CA note".
_CA_BUNDLE = Path.home() / ".config" / "rekall" / "ca-bundle.pem"
if _CA_BUNDLE.exists():
    SSL_CTX = ssl.create_default_context(cafile=_CA_BUNDLE)
else:
    try:
        import certifi
        SSL_CTX = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        SSL_CTX = ssl.create_default_context()


def http_json(url, headers=None, body=None, timeout=30, retries=5):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json", **(headers or {})})
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503) or attempt == retries:
                raise
            wait = int(e.headers.get("Retry-After") or 0) or min(2 ** attempt * 15, 300)
            log(f"  HTTP {e.code}, retrying in {wait}s ({attempt + 1}/{retries})")
            import time
            time.sleep(wait)


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"meetings": {}, "raw_ingested": [], "monday_group_id": None}


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def slugify(title, max_len=50):
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug[:max_len].rstrip("-") or "untitled"


def raw_key(path):
    """State-file entry for a raw/ file: name + short content hash, so edits re-ingest."""
    return f"{path.name}:{hashlib.sha256(path.read_bytes()).hexdigest()[:16]}"


def raw_is_pending(path, raw_ingested):
    # ponytail: bare filename entries are legacy (pre-hash) marks and match regardless of
    # content hash, so already-tracked raw files don't spuriously re-ingest on this upgrade.
    return path.name not in raw_ingested and raw_key(path) not in raw_ingested


# ── Fathom ──────────────────────────────────────────────────

def fetch_meetings(created_after, created_before):
    api_key = env("FATHOM_API_KEY")
    if not api_key:
        sys.exit("Missing FATHOM_API_KEY (run under doppler)")
    user_email = (env("WORK_EMAIL", "JIRA_EMAIL") or "").lower()

    params = urlencode({
        "created_after": created_after.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "created_before": created_before.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "include_summary": "true",
        "include_action_items": "true",
    })
    headers = {"X-Api-Key": api_key}
    items, url = [], f"{FATHOM_BASE}/meetings?{params}"
    while url:
        data = http_json(url, headers)
        items.extend(data.get("items", []))
        cursor = data.get("next_cursor")
        url = f"{FATHOM_BASE}/meetings?{params}&cursor={cursor}" if cursor else None

    meetings = []
    for item in items:
        invitees = item.get("calendar_invitees") or []
        invitee_emails = [i.get("email", "").lower() for i in invitees]
        recorded_by = (item.get("recorded_by") or {}).get("email", "").lower()
        if user_email and user_email not in invitee_emails and user_email != recorded_by:
            continue

        participants = [i.get("name") or i.get("email", "Unknown") for i in invitees]
        recorder = (item.get("recorded_by") or {}).get("name")
        if recorder and recorder not in participants:
            participants.append(recorder)

        action_items = []
        for ai in item.get("action_items") or []:
            assignee = ai.get("assignee") or {}
            action_items.append({
                "text": ai.get("description", ""),
                "assignee": assignee.get("name", ""),
                "is_mine": bool(user_email) and (assignee.get("email") or "").lower() == user_email,
                "completed": ai.get("completed", False),
            })

        when = item.get("scheduled_start_time") or item.get("created_at", "")
        try:
            dt_local = datetime.fromisoformat(when.replace("Z", "+00:00")).astimezone(CT)
        except ValueError:
            dt_local = datetime.now(CT)

        duration = None
        for s, e in [(item.get("scheduled_start_time"), item.get("scheduled_end_time")),
                     (item.get("recording_start_time"), item.get("recording_end_time"))]:
            if s and e and duration is None:
                try:
                    mins = int((datetime.fromisoformat(e.replace("Z", "+00:00"))
                                - datetime.fromisoformat(s.replace("Z", "+00:00"))).total_seconds() / 60)
                    if 0 < mins < 480:
                        duration = mins
                except ValueError:
                    pass

        meetings.append({
            "id": str(item.get("recording_id", "")),
            "title": item.get("title") or item.get("meeting_title") or "(untitled meeting)",
            "dt": dt_local,
            "duration": duration,
            "participants": participants,
            "summary": (item.get("default_summary") or {}).get("markdown_formatted", "") or "",
            "action_items": action_items,
            "url": item.get("url") or item.get("share_url", ""),
        })
    meetings.sort(key=lambda m: m["dt"])
    return meetings


def write_note(m):
    """Write meetings/{date}-{slug}.md per the /today template. Returns relative path or None if it exists."""
    date_str = m["dt"].strftime("%Y-%m-%d")
    path = MEETINGS / f"{date_str}-{slugify(m['title'])}.md"
    if path.exists():
        return None
    mine = [a for a in m["action_items"] if a["is_mine"]]
    others = [a for a in m["action_items"] if not a["is_mine"]]
    safe_title = m["title"].replace('"', "'")
    lines = [
        "---",
        "type: meeting",
        f'title: "{safe_title}"',
        f"date: {date_str}",
        "---",
        f"# {m['title']}",
        "",
        f"**Date:** {date_str} at {m['dt'].strftime('%I:%M %p').lstrip('0')}",
    ]
    if m["duration"]:
        lines.append(f"**Duration:** {m['duration']} minutes")
    if m["participants"]:
        lines.append(f"**Participants:** {', '.join(m['participants'])}")
    if m["url"]:
        lines.append(f"**Recording:** [{m['title']}]({m['url']})")
    lines += ["", "## Summary", "", m["summary"] or "_No summary from Fathom._"]
    if mine or others:
        lines += ["", "## Action Items"]
        if mine:
            lines += ["", "### Mine"] + [f"- [{'x' if a['completed'] else ' '}] {a['text']}" for a in mine]
        if others:
            lines += ["", "### Others"] + [f"- {a['assignee'] or 'Unassigned'}: {a['text']}" for a in others]
    path.write_text("\n".join(lines) + "\n")
    return str(path.relative_to(VAULT))


# ── Daily digest (today.md) ─────────────────────────────────
# The pipeline owns the marker-delimited Meeting Digest block in today.md; /today
# preserves it verbatim. First sweep of a new day archives the stale note to
# wiki/daily-notes-archive/ and starts fresh.

TODAY_NOTE = VAULT / "today.md"
ARCHIVE_DIR = VAULT / "wiki" / "daily-notes-archive"
DIGEST_START = "<!-- fathom-digest:start -->"
DIGEST_END = "<!-- fathom-digest:end -->"


def _today_skeleton(date_str, dt_local):
    return (
        "---\n"
        "type: daily\n"
        f"date: {date_str}\n"
        "tags:\n  - daily\n"
        "generated-skeleton: fathom-pipeline\n"
        "---\n"
        f"# {dt_local.strftime('%A, %B %-d, %Y')}\n\n"
        "*(Skeleton from the Fathom pipeline — run /today for the full worksheet. "
        "The Meeting Digest below grows with each hourly sweep.)*\n\n"
        "## Meeting Digest\n\n"
        f"{DIGEST_START}\n"
        f"{DIGEST_END}\n"
    )


def rollover_today_note():
    """Archive a stale today.md and start today's skeleton. Runs every sweep."""
    today_str = datetime.now(CT).strftime("%Y-%m-%d")
    if TODAY_NOTE.exists():
        text = TODAY_NOTE.read_text()
        m = re.search(r"^date:\s*(\d{4}-\d{2}-\d{2})", text, re.M)
        note_date = m.group(1) if m else None
        if note_date == today_str:
            return
        target = ARCHIVE_DIR / f"{note_date or 'undated-' + today_str}.md"
        if target.exists():
            # /today (or an earlier run) already archived that day; keep the newer
            # digest by appending our block if the archive lacks one.
            if DIGEST_START in text and DIGEST_START not in target.read_text():
                block = text[text.index(DIGEST_START):text.index(DIGEST_END) + len(DIGEST_END)]
                target.write_text(target.read_text().rstrip("\n")
                                  + f"\n\n## Meeting Digest\n\n{block}\n")
            TODAY_NOTE.unlink()
        else:
            ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
            TODAY_NOTE.rename(target)
        log(f"  today.md rolled over: {note_date or '?'} -> archive; fresh skeleton for {today_str}")
    TODAY_NOTE.write_text(_today_skeleton(today_str, datetime.now(CT)))


def digest_summary(md):
    """Compact form of a Fathom summary for the digest: prefer the Key Takeaways
    section (the full summary lives in the meeting note), and demote embedded
    headings so they can't outrank the digest's own structure."""
    m = re.search(r"^#{1,3} Key Takeaways\s*\n(.*?)(?=^#{1,3} |\Z)", md, re.M | re.S)
    body = (m.group(1) if m else md).strip()
    return re.sub(r"^(#{1,3}) ", lambda h: "#" * min(len(h.group(1)) + 2, 6) + " ", body, flags=re.M)


def digest_entry(m, note_rel, pushed_monday):
    date_str = m["dt"].strftime("%Y-%m-%d")
    today_str = datetime.now(CT).strftime("%Y-%m-%d")
    when = m["dt"].strftime("%I:%M %p").lstrip("0")
    if date_str != today_str:
        when = f"{date_str} {when}"
    head = f"### {when} — {m['title']}" + (f" ({m['duration']} min)" if m["duration"] else "")
    lines = [head, f"[[{Path(note_rel).stem}]]"
             + (f" · {len(m['participants'])} participants" if m["participants"] else ""), ""]
    lines.append(digest_summary(m["summary"]) or "_No summary from Fathom._")
    mine = [a for a in m["action_items"] if a["is_mine"] and not a["completed"] and a["text"].strip()]
    if mine:
        lines += ["", "**My to-dos:**"]
        lines += [f"- [ ] {a['text'].strip()}" + (" *(→ Monday)*" if pushed_monday else "") for a in mine]
    return "\n".join(lines)


def append_digest(entries):
    """Insert digest entries before the end marker in today.md."""
    if not entries:
        return
    text = TODAY_NOTE.read_text()
    if DIGEST_END not in text:
        # /today rewrote the note without the block; re-add it at the end.
        text = text.rstrip("\n") + f"\n\n## Meeting Digest\n\n{DIGEST_START}\n{DIGEST_END}\n"
    joined = "\n\n".join(entries)
    text = text.replace(DIGEST_END, f"{joined}\n\n{DIGEST_END}", 1)
    TODAY_NOTE.write_text(text)
    log(f"  digest: {len(entries)} entr{'y' if len(entries) == 1 else 'ies'} appended to today.md")


# ── Monday ──────────────────────────────────────────────────

def monday_gql(query, variables=None):
    token = env("MONDAY_API_TOKEN")
    if not token:
        sys.exit("Missing MONDAY_API_TOKEN (set it in .env or run under doppler)")
    data = http_json("https://api.monday.com/v2", {"Authorization": token, "API-Version": "2024-10"},
                     {"query": query, "variables": variables or {}})
    if data.get("errors"):
        raise RuntimeError(f"Monday API error: {data['errors']}")
    return data["data"]


def ensure_group(state):
    if state.get("monday_group_id"):
        return state["monday_group_id"]
    groups = monday_gql(f"query {{ boards(ids: [{MONDAY_BOARD}]) {{ groups {{ id title }} }} }}")["boards"][0]["groups"]
    for g in groups:
        if g["title"] == MONDAY_GROUP:
            state["monday_group_id"] = g["id"]
            return g["id"]
    created = monday_gql(
        "mutation($board: ID!, $name: String!) { create_group(board_id: $board, group_name: $name) { id } }",
        {"board": str(MONDAY_BOARD), "name": MONDAY_GROUP})
    state["monday_group_id"] = created["create_group"]["id"]
    return state["monday_group_id"]


def push_action_items(m, note_rel, group_id):
    pushed = 0
    for a in m["action_items"]:
        if not a["is_mine"] or a["completed"] or not a["text"].strip():
            continue
        item = monday_gql(
            "mutation($board: ID!, $group: String!, $name: String!) { create_item(board_id: $board, group_id: $group, item_name: $name) { id } }",
            {"board": str(MONDAY_BOARD), "group": group_id, "name": a["text"].strip()[:255]})
        body = (f"From meeting: {m['title']} ({m['dt'].strftime('%Y-%m-%d')})\n"
                f"Vault note: {note_rel}\n" + (f"Recording: {m['url']}" if m["url"] else ""))
        monday_gql("mutation($item: ID!, $body: String!) { create_update(item_id: $item, body: $body) { id } }",
                   {"item": item["create_item"]["id"], "body": body})
        pushed += 1
    return pushed


# ── Wiki ingest (headless claude) ───────────────────────────

def verify_ingest(source_paths):
    """Cheap, dumb post-ingest check: did the log move, and does every source show up
    somewhere in the wiki. No LLM calls -- a plain substring scan."""
    text = "".join(
        f.read_text(errors="ignore")
        for d in WIKI_TYPED_DIRS for f in (VAULT / "wiki" / d).glob("*.md")
    )
    for s in source_paths:
        basename = Path(s).stem
        if basename not in text:
            return False, f"source not referenced anywhere in the wiki: {s}"
    return True, None


def ingest_to_wiki(source_paths, extra=""):
    """Run headless claude over a batch of source paths. Returns True on success."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logfile = LOG_DIR / f"ingest-{datetime.now().strftime('%Y%m%d-%H%M%S')}.log"
    log_before_mtime = WIKI_LOG.stat().st_mtime if WIKI_LOG.exists() else 0
    prompt = (
        "You are the automated wiki ingest pipeline (unattended -- no questions, no discussion). "
        "Read wiki/CLAUDE.md (structure source of truth) and ~/.claude/skills/wiki/SKILL.md "
        "(Ingest mode) and follow both exactly; CLAUDE.md wins on structure. "
        "Every page you create or update includes generated: {by: fathom-pipeline, at: <ISO 8601 "
        "UTC>} in its frontmatter -- the docs don't know this pipeline is the caller.\nSources:\n"
        + "\n".join(f"- {p}" for p in source_paths)
        + "\nDo NOT edit wiki/index.md -- it is regenerated automatically from page frontmatter; "
        "ensure every page you create or update has title and description frontmatter. "
        "Append ONE log entry at the END of wiki/log.md covering this batch."
        + (f"\nAdditional instructions for this batch: {extra}" if extra else "")
    )
    cmd = ["claude", "-p", prompt, "--model", "sonnet",
           "--permission-mode", "acceptEdits",
           "--allowedTools", "Read,Glob,Grep,Write,Edit",
           "--output-format", "stream-json", "--verbose"]
    # Doppler injects ANTHROPIC_API_KEY; strip it so claude uses the subscription login, not API billing
    import os
    clean_env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
    # Stream claude's events into the logfile timestamped and truncated, so after
    # a timeout kill the last line names what the session was doing when it hung.
    proc = subprocess.Popen(cmd, cwd=VAULT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            env=clean_env, text=True)
    timed_out = threading.Event()
    watchdog = threading.Timer(2400, lambda: (timed_out.set(), proc.kill()))
    watchdog.start()
    with open(logfile, "w") as f:
        for line in proc.stdout:
            f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {line.rstrip()[:300]}\n")
            f.flush()
    returncode = proc.wait()
    watchdog.cancel()
    if timed_out.is_set():
        log(f"  ingest batch of {len(source_paths)}: TIMEOUT after 2400s (log: {logfile})")
        return False
    log(f"  ingest batch of {len(source_paths)}: exit {returncode} (log: {logfile})")
    if returncode != 0:
        return False
    if not WIKI_LOG.exists() or WIKI_LOG.stat().st_mtime <= log_before_mtime:
        log(f"  ingest batch of {len(source_paths)}: verification failed (wiki/log.md not updated)")
        return False
    ok, reason = verify_ingest(source_paths)
    if not ok:
        log(f"  ingest batch of {len(source_paths)}: verification failed ({reason})")
        return False
    return True


# ── Main ────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=int, default=26)
    ap.add_argument("--since", help="backfill start date YYYY-MM-DD (implies --no-monday)")
    ap.add_argument("--no-monday", action="store_true")
    ap.add_argument("--no-wiki", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    lock_fh = open(LOCK_FILE, "w")
    try:
        fcntl.flock(lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        log("another pipeline run is active; exiting")
        return
    # ponytail: lock_fh stays open (never closed) so the flock holds for the whole run;
    # the OS releases it automatically on process exit.

    now = datetime.now(timezone.utc)
    if not args.no_monday and not env("MONDAY_API_TOKEN"):
        log("no MONDAY_API_TOKEN set; skipping the Monday push")
        args.no_monday = True
    if args.since:
        start = datetime.strptime(args.since, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        args.no_monday = True  # backfill never pushes to Monday
    else:
        start = now - timedelta(hours=args.hours)

    state = load_state()
    meetings = fetch_meetings(start, now)
    new = [m for m in meetings if m["id"] not in state["meetings"]]
    log(f"{len(meetings)} meetings in window, {len(new)} new")

    if args.dry_run:
        for m in new:
            mine = sum(1 for a in m["action_items"] if a["is_mine"] and not a["completed"])
            log(f"  would process: {m['dt'].strftime('%Y-%m-%d')} {m['title']} ({mine} of my action items)")
        pending_raw = [f.name for f in sorted(RAW.glob("*.md")) if raw_is_pending(f, state["raw_ingested"])]
        log(f"  would ingest raw/: {pending_raw}")
        return

    # 0. daily digest rollover: first sweep of a new day archives yesterday's
    # today.md and starts fresh, meetings or not
    rollover_today_note()

    # 1. meeting notes + Monday + digest
    group_id = None
    monday_broken = False  # a Monday outage must never block wiki ingest
    digest_entries = []
    for m in new:
        note_rel = write_note(m)
        if note_rel is None:
            note_rel = f"wiki/meetings/{m['dt'].strftime('%Y-%m-%d')}-{slugify(m['title'])}.md"
            log(f"  note exists, skipping write: {note_rel}")
        else:
            log(f"  wrote {note_rel}")
        entry = {"note": note_rel, "monday": False, "ingested": False, "title": m["title"]}
        if not args.no_monday and not monday_broken:
            try:
                if group_id is None:
                    group_id = ensure_group(state)
                n = push_action_items(m, note_rel, group_id)
                entry["monday"] = True
                if n:
                    log(f"  pushed {n} action items to Monday")
            except Exception as e:
                monday_broken = True
                notify(f"Monday push failed ({type(e).__name__}: {e}); continuing with wiki ingest")
        digest_entries.append(digest_entry(m, note_rel, entry["monday"]))
        state["meetings"][m["id"]] = entry
        save_state(state)
    append_digest(digest_entries)

    # 2. wiki ingest: new notes + previously failed + new raw files
    if not args.no_wiki:
        failures = state.setdefault("ingest_failures", {})  # source path -> consecutive failure count
        pending_notes = [(mid, e) for mid, e in state["meetings"].items() if not e["ingested"]]
        pending_raw = [f for f in sorted(RAW.glob("*.md")) if raw_is_pending(f, state["raw_ingested"])]
        sources = [e["note"] for _, e in pending_notes] + [f"wiki/raw/{f.name}" for f in pending_raw]
        quarantined = [s for s in sources if failures.get(s, 0) >= 2]
        if quarantined:
            log(f"  skipping {len(quarantined)} quarantined source(s): {quarantined}")
        sources = [s for s in sources if failures.get(s, 0) < 2]
        log(f"wiki ingest: {len(sources)} pending sources")

        def mark_ingested(s):
            for mid, e in state["meetings"].items():
                if e["note"] == s:
                    e["ingested"] = True
            if s.startswith("wiki/raw/"):
                key = raw_key(RAW / s[len("wiki/raw/"):])
                if key not in state["raw_ingested"]:
                    state["raw_ingested"].append(key)
            failures.pop(s, None)

        for i in range(0, len(sources), INGEST_BATCH):
            batch = sources[i:i + INGEST_BATCH]
            if ingest_to_wiki(batch):
                for s in batch:
                    mark_ingested(s)
                save_state(state)
                continue
            # Batch failed: retry each source alone so one poison file can't block the queue forever.
            log("  batch failed; retrying sources individually")
            any_ok = False
            for s in batch:
                if ingest_to_wiki([s]):
                    mark_ingested(s)
                    any_ok = True
                else:
                    failures[s] = failures.get(s, 0) + 1
                    log(f"  source failed ({failures[s]}x): {s}")
                    if failures[s] >= 2:
                        notify(f"ingest source quarantined after {failures[s]} failures: {s}")
                save_state(state)
            if not any_ok:
                notify("wiki ingest failed for every source in a batch; likely systemic, stopping this run")
                break

        # Index is derived from page frontmatter; regenerate deterministically after ingest
        # rather than trusting the headless agent to hand-edit a contended catalog file.
        if any(e["ingested"] for e in state["meetings"].values()) or state["raw_ingested"]:
            regen = subprocess.run(
                ["python3", str(Path(__file__).parent / "wiki-index.py")],
                capture_output=True, text=True, timeout=120)
            log(f"  index regen: exit {regen.returncode} ({regen.stdout.strip() or regen.stderr.strip()})")

    # 3. wins sweep: roll `### Wins` bullets from session digests onto the accomplishments page
    sweep = subprocess.run(["python3", str(Path(__file__).parent / "wins-sweep.py")],
                           capture_output=True, text=True, timeout=60)
    log(f"  {sweep.stdout.strip() or sweep.stderr.strip()}")

    log("done")


if __name__ == "__main__":
    try:
        main()
    except SystemExit as e:
        if e.code not in (0, None):
            notify(f"aborted: {e.code}")
        raise
    except Exception as e:
        notify(f"crashed: {type(e).__name__}: {e}")
        raise
