#!/usr/bin/env python3
"""Follow-ups ledger: the meeting to-dos you and your tracked people own, aged.

Harvests the structured action blocks of every meeting note in wiki/meetings/
(the `## Action Items` block the Fathom pipeline writes, and the `## Next Steps`
block Fathom and Granola summaries carry), keeps only rows owned by you or by a
person listed under [cos.tracked] in rekall.toml, and ages them in business days.
Everyone else's items stay in the note and are never read again.

State is one JSON file, STATE_DIR/follow-ups.json. Re-harvesting updates text
and source but never resurrects a row you marked done or dropped.

  followups.py                 harvest, then print the snapshot JSON (default)
                               (waiting_on passes through Monday On Hold items when
                               [cos] monday_snapshot is set; a missing feed never blinds the ledger)
  followups.py show            print the open rows as a table
  followups.py done ID...      mark rows done (IDs are the 12-char ids from show)
  followups.py drop ID...      mark rows dropped; they never come back
  followups.py nudged ID...    record that you nudged the owners today
  followups.py render          read ticked boxes, harvest, rewrite the today.md block
  followups.py reset           drop every open row and harvest only notes dated today or later

In today.md, tick `[x]` on a row for done or `[-]` to drop it; the next render
(every Fathom sweep, or by hand) records it in the ledger.

Snapshot contract (same shape as familiar's monday-board-snapshot.py): one JSON
object, status ok|blind, errors[], every bucket carries `found` so an empty
bucket is a number, never a missing key. Every row quotes its source line.
"""
import hashlib
import json
import re
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rekall_config import COS_GITHUB_ORGS, COS_ME, COS_MONDAY_SNAPSHOT, COS_TRACKED, STATE_DIR, VAULT, WIKI  # noqa: E402

import gh  # noqa: E402  (same folder)

MEETINGS = WIKI / "meetings"
LEDGER = STATE_DIR / "follow-ups.json"
TODAY_NOTE = VAULT / "today.md"
BLOCK_START = "<!-- cos-followups:start -->"
BLOCK_END = "<!-- cos-followups:end -->"

STALE_BDAYS = 5      # open this many business days without a nudge = stale
LOOKBACK_DAYS = 60   # notes older than this are not harvested
DONE_WINDOW = 7      # closed_this_week window

# ── owners ────────────────────────────────────────────────────

def _norm(name):
    return re.sub(r"[^a-z ]", "", name.lower()).strip()

ME_ALIASES = {_norm(n) for n in COS_ME}
TRACKED_ALIASES = {}
for _display, _aliases in COS_TRACKED.items():
    for _a in [_display, *_aliases]:
        TRACKED_ALIASES[_norm(_a)] = _display


def owner_of(name):
    """'me', a tracked display name, or None for everyone else."""
    n = _norm(name or "")
    if n in ME_ALIASES:
        return "me"
    return TRACKED_ALIASES.get(n)


# ── parsing ───────────────────────────────────────────────────

# `- [**Owner:** text](link)` and `- **Owner:** text`
RE_OWNER_COLON = re.compile(r"^\s*-\s+\[?\*\*([^*:]+?):\*\*\s*(.*?)\]?(?:\(\S+\))?\s*$")
# `- **text** (Owner)`
RE_PAREN_OWNER = re.compile(r"^\s*-\s+\*\*(.+?)\*\*\s*\(([^()]+)\)\s*$")
# `- Owner to do the thing`
RE_NAME_TO = re.compile(r"^\s*-\s+([A-Z][a-z]+(?: [A-Z][a-z]+)?) to (.+?)\s*$")
# `- Owner: text` (Fathom pipeline's ### Others)
RE_PLAIN_COLON = re.compile(r"^\s*-\s+([A-Z][A-Za-z .'-]+?):\s+(.+?)\s*$")
# `- [ ] text` / `- [x] text` (### Mine)
RE_CHECKBOX = re.compile(r"^\s*-\s+\[([ xX])\]\s+(.+?)\s*$")
# `- [text](link)` nested under a grouped owner
RE_LINKED = re.compile(r"^\s*-\s+\[(.+?)\]\(\S+\)\s*$")
RE_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")


def _clean(text):
    text = re.sub(r"\[([^\]]+)\]\(\S+\)", r"\1", text)  # strip links, keep label
    return text.strip(" *").strip()


def parse_note(text):
    """Yield (owner_label, item_text, done, source_line) for the rows this ledger keeps.

    Only the Action Items and Next Steps blocks are read. Deeper sub-bullets are
    details of the item above them, except under a grouped `- [**Owner:**](link)`
    line, where they are the owner's items.
    """
    section = None       # "mine", "others", "next", or None
    group_owner = None   # owner from a `- [**Name:**](link)` line with no text
    group_indent = -1
    for raw in text.splitlines():
        h = RE_HEADING.match(raw)
        if h:
            title = h.group(2).strip().lower()
            if title.startswith("action items"):
                section = "actions"
            elif title == "mine" and section in ("actions", "mine", "others"):
                section = "mine"
            elif title == "others" and section in ("actions", "mine", "others"):
                section = "others"
            elif title.startswith("next steps"):
                section = "next"
            else:
                section = None
            group_owner, group_indent = None, -1
            continue
        if section is None or not raw.strip().startswith("-"):
            continue
        indent = len(raw) - len(raw.lstrip())
        src = raw.strip()

        if section == "mine":
            m = RE_CHECKBOX.match(raw)
            if m and indent <= 2:
                yield "me", _clean(m.group(2)), m.group(1).lower() == "x", src
            continue

        if section == "others":
            m = RE_PLAIN_COLON.match(raw)
            if m and indent <= 2:
                o = owner_of(m.group(1))
                if o:
                    yield o, _clean(m.group(2)), False, src
            continue

        # Next Steps
        if group_owner is not None and indent > group_indent:
            m = RE_LINKED.match(raw) or RE_CHECKBOX.match(raw)
            if m:
                item = m.group(2) if m.re is RE_CHECKBOX else m.group(1)
                yield group_owner, _clean(item), False, src
            continue
        group_owner, group_indent = None, -1
        if indent > 2:
            continue  # detail of the item above
        m = RE_OWNER_COLON.match(raw)
        if m:
            o = owner_of(m.group(1))
            item = _clean(m.group(2))
            if not item:  # grouped form: items follow, nested
                if o:
                    group_owner, group_indent = o, indent
                continue
            if o:
                yield o, item, False, src
            continue
        m = RE_PAREN_OWNER.match(raw)
        if m:
            o = owner_of(m.group(2))
            if o:
                yield o, _clean(m.group(1)), False, src
            continue
        m = RE_NAME_TO.match(raw)
        if m:
            o = owner_of(m.group(1))
            if o:
                yield o, _clean(m.group(0)[m.group(0).index("-") + 1:]), False, src
            continue
        m = RE_PLAIN_COLON.match(raw)
        if m and "**" not in raw:
            o = owner_of(m.group(1))
            if o:
                yield o, _clean(m.group(2)), False, src


def note_date(path, text):
    m = re.search(r"^date:\s*(\d{4}-\d{2}-\d{2})", text, re.M)
    if m:
        return date.fromisoformat(m.group(1))
    m = re.match(r"(\d{4}-\d{2}-\d{2})", path.name)
    return date.fromisoformat(m.group(1)) if m else None


def row_id(source, text):
    return hashlib.sha1(f"{source}\n{_norm(text)}".encode()).hexdigest()[:12]


# ── ledger ────────────────────────────────────────────────────

def load():
    if LEDGER.exists():
        return json.loads(LEDGER.read_text())
    return {"rows": {}}


def save(ledger):
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    LEDGER.write_text(json.dumps(ledger, indent=1, ensure_ascii=False))


def bdays_between(start, end):
    if end <= start:
        return 0
    n, d = 0, start
    while d < end:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n += 1
    return n


def harvest(ledger, today):
    """Merge every kept row from recent meeting notes into the ledger. Returns errors[]."""
    errors = []
    if not MEETINGS.is_dir():
        return [f"{MEETINGS} is not a directory"]
    cutoff = today - timedelta(days=LOOKBACK_DAYS)
    if ledger.get("since"):  # set by `reset`: notes before this date are never harvested
        cutoff = max(cutoff, date.fromisoformat(ledger["since"]))
    seen = set()
    for path in sorted(MEETINGS.glob("*.md")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as e:
            errors.append(f"{path.name}: {e}")
            continue
        d = note_date(path, text)
        if d is None or d < cutoff:
            continue
        source = str(path.relative_to(VAULT))
        for owner, item, done, src in parse_note(text):
            if not item:
                continue
            rid = row_id(source, item)
            seen.add(rid)
            row = ledger["rows"].get(rid)
            if row is None:
                row = ledger["rows"][rid] = {
                    "id": rid, "owner": owner, "text": item, "source": source, "quote": src,
                    "opened": d.isoformat(), "status": "open", "last_nudge": None, "closed": None,
                }
            else:
                row.update(text=item, quote=src, source=source)
            # the source checkbox is authoritative for "done"; dropped stays dropped
            if done and row["status"] == "open":
                row["status"], row["closed"] = "done", today.isoformat()
    return errors


def waiting_on():
    """Monday On Hold items, passed through from the snapshot script. Returns (bucket, error|None).

    The feed is optional: missing, slow, broken, or blind all give an empty bucket
    and one error line. The ledger itself is never blinded by it.
    """
    empty = {"found": 0, "items": []}
    if COS_MONDAY_SNAPSHOT is None:
        return empty, None
    if not COS_MONDAY_SNAPSHOT.exists():
        return empty, f"waiting_on: monday snapshot missing: {COS_MONDAY_SNAPSHOT}"
    try:
        p = subprocess.run([sys.executable, str(COS_MONDAY_SNAPSHOT)], capture_output=True, text=True, timeout=60)
        out = json.loads(p.stdout)
    except subprocess.TimeoutExpired:
        return empty, "waiting_on: monday snapshot timed out after 60s"
    except (OSError, ValueError) as e:
        return empty, f"waiting_on: monday snapshot failed: {e}"
    if out.get("status") != "ok":
        # its errors[] are {source, message} dicts
        why = "; ".join(e.get("message", str(e)) if isinstance(e, dict) else str(e) for e in out.get("errors", [])) or "no reason given"
        return empty, f"waiting_on: monday snapshot blind: {why}"
    items = out.get("on_hold", [])
    return {"found": len(items), "items": items}, None


def snapshot(ledger, today, errors):
    rows = list(ledger["rows"].values())
    waiting, w_err = waiting_on()
    errors = errors + [w_err] if w_err else errors
    # GitHub: my open PRs without approval, and reviews requested of me. Optional feed, never blinds the ledger.
    prs_waiting, reviews = [], []
    try:
        prs_waiting = gh.waiting(gh.open_prs(COS_GITHUB_ORGS, today))
        reviews = gh.review_requests(COS_GITHUB_ORGS)
    except Exception as e:  # ponytail: gh missing or offline is one error line, not a crash
        errors = errors + [f"github: {e}"]
    def enrich(r):
        opened = date.fromisoformat(r["opened"])
        age = bdays_between(opened, today)
        since_nudge = bdays_between(date.fromisoformat(r["last_nudge"]), today) if r["last_nudge"] else None
        return {**r, "age_bdays": age,
                "stale": age >= STALE_BDAYS and (since_nudge is None or since_nudge >= STALE_BDAYS)}
    open_rows = sorted((enrich(r) for r in rows if r["status"] == "open"), key=lambda r: r["opened"])
    def bucket(items):
        return {"found": len(items), "items": items}
    tracked = {name: bucket([r for r in open_rows if r["owner"] == name]) for name in COS_TRACKED}
    closed = [r for r in rows if r["status"] == "done" and r["closed"]
              and date.fromisoformat(r["closed"]) >= today - timedelta(days=DONE_WINDOW)]
    return {
        "generated": datetime.now().isoformat(timespec="seconds"),
        "status": "blind" if [e for e in errors if not e.startswith(("waiting_on:", "github:"))] and not rows else "ok",
        "errors": errors,
        "thresholds": {"stale_bdays": STALE_BDAYS, "lookback_days": LOOKBACK_DAYS, "done_window_days": DONE_WINDOW},
        "owed_by_me": bucket([r for r in open_rows if r["owner"] == "me"]),
        "tracked": tracked,
        "waiting_on": waiting,
        "prs_waiting": bucket(prs_waiting),
        "reviews_owed": bucket(reviews),
        "closed_this_week": bucket(sorted(closed, key=lambda r: r["closed"], reverse=True)),
        "ledger": str(LEDGER),
    }


# ── render ────────────────────────────────────────────────────

def render_block(snap):
    def line(r):
        flag = " **stale**" if r["stale"] else ""
        return f"- [ ] {r['text']} · {r['age_bdays']}bd · `{r['id']}` · [[{Path(r['source']).stem}]]{flag}"
    out = [BLOCK_START, "## Follow-ups", ""]
    if snap["status"] == "blind":
        out += [f"Follow-ups is blind since {snap['generated'][11:16]}: {'; '.join(snap['errors'])}", BLOCK_END]
        return "\n".join(out)
    me = snap["owed_by_me"]
    out += [f"**You owe ({me['found']})**"] + [line(r) for r in me["items"]] + [""]
    for name, b in snap["tracked"].items():
        out += [f"**{name} owes ({b['found']})**"] + [line(r) for r in b["items"]] + [""]
    # Monday items, not ledger rows: no checkbox, no id, so sync_today never touches them
    def hold(i):
        s = f"- {i['name']} · {i.get('project') or 'no project'} · {i['business_days_idle']} business days on hold"
        if i.get("last_comment"):
            s += f' · "{i["last_comment"]}"'
        s += f" · [link]({i['url']})"
        if i.get("checkin_due"):
            s += " · check in"
        if not i.get("mine", True):
            s += " · not yours"
        return s
    # PRs: no checkbox, no id either
    def pr(i):
        return f"- PR [#{i['number']}]({i['url']}) · {i['repo']} · {i['title']} · {i['wait_bdays']} business days without approval ({i['review'].lower().replace('_', ' ')})"
    w, pw, rv = snap["waiting_on"], snap.get("prs_waiting", {"found": 0, "items": []}), snap.get("reviews_owed", {"found": 0, "items": []})
    w_err = next((e for e in snap["errors"] if e.startswith("waiting_on:")), None)
    g_err = next((e for e in snap["errors"] if e.startswith("github:")), None)
    if w_err:
        out += [f"Waiting on is blind: {w_err.split(': ', 1)[1]}", ""]
    if w["found"] or pw["found"]:
        out += [f"**Waiting on ({w['found'] + pw['found']})**"] + [hold(i) for i in w["items"]] + [pr(i) for i in pw["items"]] + [""]
    if g_err:
        out += [f"GitHub is blind: {g_err.split(': ', 1)[1]}", ""]
    if rv["found"]:
        out += [f"**Reviews you owe ({rv['found']})**"] + [f"- [#{i['number']}]({i['url']}) · {i['repo']} · {i['title']} · by {i['author']}" for i in rv["items"]] + [""]
    c = snap["closed_this_week"]
    out += [f"**Closed this week ({c['found']})**"] + [f"- [x] {r['text']} · {r['closed']}" for r in c["items"]]
    other = [e for e in snap["errors"] if e not in (w_err, g_err)]
    if other:
        out += ["", "Errors: " + "; ".join(other)]
    out += ["", "_Tick `[x]` for done or `[-]` to drop; the next render records it. "
                f"Or `followups.py done|drop|nudged ID`. Ledger `{snap['ledger']}`_", BLOCK_END]
    return "\n".join(out)


RE_TICKED = re.compile(r"^\s*-\s+\[([xX-])\]\s.*`([0-9a-f]{12})`")


def sync_today(ledger, today):
    """Honor checkboxes ticked in the block we wrote last time: [x] = done, [-] = dropped."""
    if not TODAY_NOTE.exists():
        return 0
    text = TODAY_NOTE.read_text(encoding="utf-8")
    if BLOCK_START not in text or BLOCK_END not in text:
        return 0
    block = text[text.index(BLOCK_START):text.index(BLOCK_END)]
    n = 0
    for line in block.splitlines():
        m = RE_TICKED.match(line)
        if not m:
            continue
        row = ledger["rows"].get(m.group(2))
        if row and row["status"] == "open":
            row["status"] = "done" if m.group(1).lower() == "x" else "dropped"
            row["closed"] = today.isoformat()
            n += 1
    return n


def write_today(block):
    text = TODAY_NOTE.read_text(encoding="utf-8") if TODAY_NOTE.exists() else ""
    if BLOCK_START in text and BLOCK_END in text:
        a, b = text.index(BLOCK_START), text.index(BLOCK_END) + len(BLOCK_END)
        text = text[:a] + block + text[b:]
    else:
        text = text.rstrip("\n") + "\n\n" + block + "\n"
    TODAY_NOTE.write_text(text, encoding="utf-8")


# ── verbs ─────────────────────────────────────────────────────

def mark(ledger, rids, status, today):
    for rid in rids:
        row = ledger["rows"].get(rid)
        if row is None:
            sys.exit(f"no row {rid} (nothing written)")
    for rid in rids:
        row = ledger["rows"][rid]
        if status == "nudged":
            row["last_nudge"] = today.isoformat()
        else:
            row["status"], row["closed"] = status, today.isoformat()
        print(f"{rid}: {status} · {row['text']}")
    save(ledger)


def main(argv):
    today = date.today()
    ledger = load()
    verb = argv[0] if argv else "snapshot"
    if verb == "reset":
        # clean slate: every open row is dropped and only notes dated from today on are harvested
        n = 0
        for row in ledger["rows"].values():
            if row["status"] == "open":
                row["status"], row["closed"], n = "dropped", today.isoformat(), n + 1
        ledger["since"] = today.isoformat()
        save(ledger)
        print(f"dropped {n} open rows; harvesting notes dated {today} and later only")
        return
    if verb in ("done", "drop", "nudged"):
        if len(argv) < 2:
            sys.exit(f"usage: followups.py {verb} ID [ID ...]")
        status = {"done": "done", "drop": "dropped", "nudged": "nudged"}[verb]
        return mark(ledger, argv[1:], status, today)
    ticked = sync_today(ledger, today)
    errors = harvest(ledger, today)
    save(ledger)
    snap = snapshot(ledger, today, errors)
    if verb == "show":
        for r in snap["owed_by_me"]["items"] + [r for b in snap["tracked"].values() for r in b["items"]]:
            who = "me" if r["owner"] == "me" else r["owner"]
            print(f"{r['id']}  {r['age_bdays']:>3}bd  {who:<12} {r['text'][:80]}")
        print(f"\n{snap['owed_by_me']['found']} mine · "
              + " · ".join(f"{n} {b['found']}" for n, b in snap['tracked'].items())
              + f" · waiting on {snap['waiting_on']['found']} · {snap['closed_this_week']['found']} closed this week")
    elif verb == "render":
        write_today(render_block(snap))
        print(f"wrote follow-ups block to {TODAY_NOTE}" + (f" ({ticked} ticked boxes recorded)" if ticked else ""))
    else:
        print(json.dumps(snap, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv[1:])
