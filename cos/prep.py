#!/usr/bin/env python3
"""Meeting prep: for each meeting on the calendar, the thread it belongs to, from the wiki.

For every event today with two or more people (the only gate), a short brief:
  Bring        to-dos from the prior notes that became Monday tickets (with status), what
               you still owe the people in the room (ledger rows, any meeting), a tracked
               person's open items when they are present, and unanswered questions from
               last time (lines ending in ? in Next Steps or Blockers)
  Background   the project page's State in two sentences, the last meeting (how long ago,
               one-line summary), what changed on the project page since then, and the
               line in a recent note that spawned this meeting when there is one; the
               invite text only when nothing earlier exists

Reads only. Calendar via Microsoft Graph with the read-only scope string; writes one
marker block into today.md and nothing else.

  prep.py                  every meeting today -> today.md block (default)
  prep.py next             only the next meeting that hasn't started
  prep.py "title text"     meetings whose subject contains the text
  prep.py --date YYYY-MM-DD   another day (testing against past notes)
  prep.py --json           print the facts instead of writing the block

Secrets: MSGRAPH_CLIENT_ID, MSGRAPH_CLIENT_SECRET, MSGRAPH_REFRESH_TOKEN, MSGRAPH_TENANT_ID
from the environment (.env) or Doppler, same as the pipeline.
"""
import importlib.util
import json
import os
import re
import subprocess
import sys
import urllib.parse
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from rekall_config import COS_ME, COS_MONDAY_SNAPSHOT, COS_TRACKED, STATE_DIR, TIMEZONE, VAULT, WIKI  # noqa: E402

import gh  # noqa: E402
import projects  # noqa: E402

# reuse the pipeline's HTTP helper (corporate CA bundle, retries) and env lookup
_spec = importlib.util.spec_from_file_location("fp", ROOT / "scripts" / "fathom-pipeline.py")
fp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fp)

MEETINGS = WIKI / "meetings"
PAGES = WIKI / "pages"
LEDGER = STATE_DIR / "follow-ups.json"
TODAY_NOTE = VAULT / "today.md"
BLOCK_START = "<!-- cos-prep:start -->"
BLOCK_END = "<!-- cos-prep:end -->"
TZ = ZoneInfo(TIMEZONE)

READ_SCOPE = "User.Read Calendars.Read Mail.Read Team.ReadBasic.All Channel.ReadBasic.All Chat.ReadBasic Chat.Read"
SAME_TITLE_DAYS = 90
OVERLAP_DAYS = 14
SPAWN_RE = re.compile(r"\b(schedule|set up|setup|follow[- ]?up|separate meeting|next meeting|sync|align)\b", re.I)
STOP = {"meeting", "call", "sync", "weekly", "daily", "standup", "stand", "check", "review", "with", "and", "the",
        "team", "project", "discussion", "chat", "quick", "biweekly", "monthly"}

log = lambda m: print(f"[prep] {m}", file=sys.stderr)  # noqa: E731


# ── secrets / Graph ───────────────────────────────────────────

def secret(name):
    v = os.environ.get(name)
    if v:
        return v.strip()
    try:
        return subprocess.run(["doppler", "secrets", "get", name, "--project", "heckatron", "--config", "dev", "--plain"],
                              capture_output=True, text=True, timeout=20).stdout.strip() or None
    except Exception:
        return None


def graph_token():
    ids = {k: secret(k) for k in ("MSGRAPH_CLIENT_ID", "MSGRAPH_CLIENT_SECRET", "MSGRAPH_REFRESH_TOKEN", "MSGRAPH_TENANT_ID")}
    missing = [k for k, v in ids.items() if not v]
    if missing:
        raise RuntimeError(f"missing {', '.join(missing)}")
    body = urllib.parse.urlencode({
        "client_id": ids["MSGRAPH_CLIENT_ID"], "client_secret": ids["MSGRAPH_CLIENT_SECRET"],
        "refresh_token": ids["MSGRAPH_REFRESH_TOKEN"], "grant_type": "refresh_token", "scope": READ_SCOPE,
    }).encode()
    req = urllib.request.Request(f"https://login.microsoftonline.com/{ids['MSGRAPH_TENANT_ID']}/oauth2/v2.0/token",
                                 data=body, headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=30, context=fp.SSL_CTX) as r:
        data = json.loads(r.read())
    if "access_token" not in data:
        raise RuntimeError(data.get("error_description", "no access_token"))
    return data["access_token"]


def fetch_events(day):
    """Today's calendar events with two or more people, in local time."""
    token = graph_token()
    start = datetime.combine(day, datetime.min.time(), TZ)
    end = start + timedelta(days=1)
    params = urllib.parse.urlencode({
        "startDateTime": start.isoformat(), "endDateTime": end.isoformat(), "$top": "50", "$orderby": "start/dateTime",
        "$select": "id,iCalUId,subject,start,end,attendees,organizer,bodyPreview,isCancelled,isAllDay,webLink,seriesMasterId",
    })
    data = fp.http_json(f"https://graph.microsoft.com/v1.0/me/calendarView?{params}",
                        headers={"Authorization": f"Bearer {token}", "Prefer": f'outlook.timezone="{TIMEZONE}"'})
    events = []
    for e in data.get("value", []):
        if e.get("isCancelled") or e.get("isAllDay"):
            continue
        people = {}
        org = (e.get("organizer") or {}).get("emailAddress") or {}
        if org.get("name"):
            people[org.get("address", org["name"]).lower()] = org["name"]
        for a in e.get("attendees") or []:
            ea = a.get("emailAddress") or {}
            if ea.get("name") and a.get("type") != "resource":
                people[ea.get("address", ea["name"]).lower()] = ea["name"]
        if len(people) < 2:
            continue
        body = " ".join((e.get("bodyPreview") or "").split())
        body = re.split(r"_{5,}|Microsoft Teams meeting|Join on your computer|Meeting ID:", body)[0].strip()
        st = datetime.fromisoformat(e["start"]["dateTime"][:19])
        events.append({
            "id": e.get("iCalUId") or e["id"], "title": e.get("subject") or "(no subject)",
            "start": st.strftime("%H:%M"), "start_iso": st.isoformat(), "end": e["end"]["dateTime"][11:16],
            "attendees": sorted(people.values()), "body": body[:400],
            "link": e.get("webLink"), "recurring": bool(e.get("seriesMasterId")),
        })
    return events


# ── wiki lookups ──────────────────────────────────────────────

def norm(s):
    return re.sub(r"[^a-z0-9 ]", " ", (s or "").lower())


def sig_words(title):
    words = {w for w in norm(title).split() if len(w) >= 3 and w not in STOP}
    # "DE Team Weekly Sync Up" has nothing left after stopwords; fall back to the whole title
    return words or {"*", " ".join(norm(title).split())}


def title_match(want, have):
    """Enough overlap to call two titles the same thread: at least half the event's
    significant words, and at least two of them when it has two or more."""
    if not want or not have:
        return False
    shared = len(want & have)
    if "*" in want:  # no significant words in the event title: whole titles must match
        return want == have
    return shared >= min(len(want), 2) and shared * 2 >= len(want)


def name_keys(name):
    """Ways a person's name appears: full, and first+last. Lowercase."""
    parts = norm(name).split()
    keys = {" ".join(parts)}
    if len(parts) >= 2:
        keys.add(f"{parts[0]} {parts[-1]}")
    return keys


def note_meta(path):
    text = path.read_text(encoding="utf-8", errors="replace")
    fm = {}
    if text.startswith("---"):
        for line in text.split("---", 2)[1].splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                fm[k.strip()] = v.strip().strip('"')
    m = re.search(r"^\*\*Participants:\*\*\s*(.+)$", text, re.M)
    participants = [re.sub(r"\s*\(.*?\)", "", p).strip() for p in m.group(1).split(",")] if m else []
    d = fm.get("date") or (re.match(r"\d{4}-\d{2}-\d{2}", path.name) or [None])[0]
    try:
        d = date.fromisoformat(d[:10]) if d else None
    except ValueError:
        d = None
    summary = ""
    if "## Summary" in text:
        for line in text.split("## Summary", 1)[1].splitlines():
            if line.strip() and not line.startswith("#"):
                summary = re.sub(r"\[([^\]]+)\]\(\S+\)", r"\1", line).strip(" *-")[:200]
                break
    return {"path": path, "stem": path.stem, "title": fm.get("title") or path.stem, "date": d,
            "participants": participants, "text": text, "summary": summary}


def recent_notes(day, days):
    out = []
    for p in MEETINGS.glob("*.md"):
        m = re.match(r"(\d{4}-\d{2}-\d{2})", p.name)
        if not m:
            continue
        d = date.fromisoformat(m.group(1))
        if day - timedelta(days=days) <= d < day:
            out.append(note_meta(p))
    return sorted(out, key=lambda n: n["date"] or date.min, reverse=True)


def prior_notes(ev, day):
    want = sig_words(ev["title"])
    others = [a for a in ev["attendees"] if not (name_keys(a) & ME_KEYS)]
    att = set().union(*(name_keys(a) for a in others)) if others else set()
    need = min(2, len(others))  # a 1:1 needs the one other person; bigger meetings need two
    same_title, overlap = [], []
    for n in recent_notes(day, SAME_TITLE_DAYS):
        if title_match(want, sig_words(n["title"])):
            same_title.append(n)
        elif need and (day - (n["date"] or date.min)).days <= OVERLAP_DAYS:
            shared = {k for p in n["participants"] for k in name_keys(p)} & att
            # a person counts once even when both "first last" and the full name matched
            if len({k.split()[-1] for k in shared}) >= need:
                overlap.append(n)
    return same_title[:2], overlap[:3]


def open_rows_for(notes):
    if not LEDGER.exists():
        return []
    stems = {n["stem"] for n in notes}
    rows = json.loads(LEDGER.read_text()).get("rows", {}).values()
    return [r for r in rows if r["status"] == "open" and Path(r["source"]).stem in stems]


def page_index():
    idx = {"person": {}, "project": {}}
    for p in PAGES.glob("*.md"):
        head = p.read_text(encoding="utf-8", errors="replace")[:1500]
        t = re.search(r"^type:\s*(\w+)", head, re.M)
        if not t or t.group(1) not in idx:
            continue
        title = re.search(r"^title:\s*\"?(.+?)\"?\s*$", head, re.M)
        name = title.group(1) if title else p.stem.replace("-", " ")
        if t.group(1) == "project":
            # a project is named many ways: title, H1, aliases, tags. Match on all of them.
            h1 = re.search(r"^# (.+)$", head, re.M)
            extra = []
            for key in ("aliases", "tags"):  # only these lists; sources: would drag in meeting filenames
                m = re.search(rf"^{key}:\s*\n((?:[ \t]+-\s+.+\n?)+)", head, re.M)
                if m:
                    extra += re.findall(r"-\s+(.+)", m.group(1))
                m = re.search(rf"^{key}:\s*\[(.+?)\]", head, re.M)  # inline [a, b] form
                if m:
                    extra += [x.strip() for x in m.group(1).split(",")]
            name = " ".join([name, h1.group(1) if h1 else "", *extra])
        idx[t.group(1)][p] = name
    return idx


def project_facts(title, idx):
    want = sig_words(title)
    best, score = None, 0
    for p, ptitle in idx["project"].items():
        have = sig_words(ptitle)
        s = len(want & have)
        if s > score and title_match(want, have):
            best, score = p, s
    if not best:
        return None
    text = best.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"^## State\s*\n+((?:.+\n?){1,3})", text, re.M)
    return {"page": best.stem, "state": " ".join(m.group(1).split())[:300] if m else ""}


def spawn_lines(ev, day):
    want = sig_words(ev["title"])
    att_first = {norm(a).split()[0] for a in ev["attendees"] if a}
    hits = []
    for n in recent_notes(day, OVERLAP_DAYS):
        in_next = False
        for line in n["text"].splitlines():
            if line.startswith("## "):
                in_next = "next step" in line.lower() or "action item" in line.lower()
                continue
            if not in_next or not line.strip().startswith("-") or not SPAWN_RE.search(line):
                continue
            words = set(norm(line).split())
            if (want & words) or len(att_first & words) >= 1 and want & words:
                hits.append({"note": n["stem"], "quote": line.strip()[:220]})
    return hits[:3]


def _norm_text(t):
    return " ".join(norm(re.sub(r"\(.*?\)|\[.*?\]", "", t)).split())


def monday_open_items():
    """Every open Monday item with status, from the snapshot script named in rekall.toml. [] if unavailable."""
    if not COS_MONDAY_SNAPSHOT or not Path(COS_MONDAY_SNAPSHOT).exists():
        return []
    try:
        out = subprocess.run([sys.executable, str(COS_MONDAY_SNAPSHOT)], capture_output=True, text=True, timeout=60).stdout
        return json.loads(out).get("open_items", [])
    except Exception as e:
        log(f"monday snapshot unavailable: {e}")
        return []


def ticketed(notes, open_items):
    """Open Monday items whose name matches an action item in the prior notes."""
    actions = set()
    for n in notes:
        in_block = False
        for line in n["text"].splitlines():
            if line.startswith("## "):
                in_block = "action item" in line.lower() or "next step" in line.lower()
                continue
            if in_block and line.strip().startswith("-"):
                actions.add(_norm_text(re.sub(r"^\s*-\s*(\[[ xX]\]\s*)?(\*\*[^*]+\*\*\s*)?", "", line)))
    out = []
    for it in open_items:
        key = _norm_text(it["name"])
        if key and any(key in a or a in key for a in actions if len(a) > 12):
            out.append({"name": it["name"], "status": it.get("status"), "url": it["url"]})
    return out[:5]


def open_questions(notes):
    """Lines ending in ? inside Next Steps, Blockers, or Questions blocks of the prior notes."""
    out = []
    for n in notes:
        in_block = False
        for line in n["text"].splitlines():
            if line.startswith("## "):
                t = line.lower()
                in_block = any(w in t for w in ("next step", "blocker", "question", "open"))
                continue
            if in_block and line.strip().startswith("-") and line.rstrip().endswith("?"):
                out.append({"note": n["stem"], "quote": _clean_md(line)[:200]})
    return out[:3]


def _clean_md(line):
    line = re.sub(r"\[([^\]]+)\]\(\S+\)", r"\1", line)
    return re.sub(r"^\s*-\s*(\[[ xX]\]\s*)?", "", line).strip(" *")


def owed_to_attendees(ev, notes):
    """Ledger rows: mine whose source note included someone in this meeting (any meeting, not only this
    series), plus a tracked person's rows when they are in the room."""
    if not LEDGER.exists():
        return [], []
    rows = [r for r in json.loads(LEDGER.read_text()).get("rows", {}).values() if r["status"] == "open"]
    others = {k for a in ev["attendees"] if not (name_keys(a) & ME_KEYS) for k in name_keys(a)}
    mine, theirs = [], []
    stems = {n["stem"] for n in notes}
    meta_cache = {}
    for r in rows:
        src = Path(r["source"]).stem
        if r["owner"] == "me":
            if src in stems:
                mine.append(r)
                continue
            if src not in meta_cache:
                path = MEETINGS / f"{src}.md"
                meta_cache[src] = note_meta(path) if path.exists() else {"participants": []}
            if {k for p in meta_cache[src]["participants"] for k in name_keys(p)} & others:
                mine.append(r)
        elif r["owner"] in COS_TRACKED and name_keys(r["owner"]) & others:
            theirs.append(r)
    return mine[:4], theirs[:3]


def since_then(project, last_date):
    """Project page Updates entries dated after the last meeting: headings only."""
    if not project or not last_date:
        return []
    text = (PAGES / f"{project['page']}.md").read_text(encoding="utf-8", errors="replace")
    out = []
    for m in re.finditer(r"^### (\d{4}-\d{2}-\d{2})[^\n]*", text, re.M):
        try:
            if date.fromisoformat(m.group(1)) > last_date:
                out.append(m.group(0)[4:].strip())
        except ValueError:
            pass
    return out[:2]


def project_prs(project, last_date, day):
    """PRs in the project's repos (from its `repos:` frontmatter) merged since the last meeting, and open ones.
    Repo-wide entries show every PR; prefixed entries only PRs whose files sit under the prefix."""
    if not project:
        return [], []
    repos = projects.project_repos().get(project["page"], [])
    since = last_date or (day - timedelta(days=OVERLAP_DAYS))
    merged, open_ = [], []
    for full_repo, prefix in repos:
        try:
            m = gh.repo_prs(full_repo, since=since, state="merged", limit=15)
            o = gh.repo_prs(full_repo, state="open", limit=15)
        except RuntimeError as e:
            log(f"github {full_repo}: {e}")
            continue
        for bucket, prs in ((merged, m), (open_, o)):
            for pr in prs:
                if prefix and not projects.covers(prefix, gh.pr_files(pr["url"])):
                    continue
                if pr["url"] not in {x["url"] for x in bucket}:
                    bucket.append(pr)
    return merged[:5], open_[:5]


def facts_for(ev, day, idx, open_items):
    same, overlap = prior_notes(ev, day)
    notes = same or overlap[:1]
    last = same[0] if same else (overlap[0] if overlap else None)
    project = project_facts(ev["title"], idx)
    mine, theirs = owed_to_attendees(ev, notes)
    return {
        **ev,
        "last": {"note": last["stem"], "date": last["date"].isoformat(), "summary": last["summary"],
                 "same_series": bool(same), "weeks_ago": round((day - last["date"]).days / 7)} if last else None,
        "ticketed": ticketed(notes, open_items),
        "owed_by_me": [{"text": r["text"], "source": Path(r["source"]).stem, "opened": r["opened"]} for r in mine],
        "owed_by_them": [{"owner": r["owner"], "text": r["text"], "source": Path(r["source"]).stem} for r in theirs],
        "open_questions": open_questions(notes),
        "project": project,
        "since_then": since_then(project, last["date"] if last else None),
        "prs": dict(zip(("merged", "open"), project_prs(project, last["date"] if last else None, day))),
        "came_from": spawn_lines(ev, day),
    }


ME_KEYS = set().union(*(name_keys(n) for n in COS_ME))


# ── render ────────────────────────────────────────────────────

def render(briefs, day, errors):
    out = [BLOCK_START, f"## Meeting prep · {day.isoformat()}", ""]
    if errors:
        out += [f"Prep is blind since {datetime.now(TZ).strftime('%H:%M')}: {'; '.join(errors)}", BLOCK_END]
        return "\n".join(out)
    if not briefs:
        out += ["No meetings with two or more people today.", BLOCK_END]
        return "\n".join(out)
    for b in briefs:
        out.append(f"### {b['start']} · {b['title']}")
        bring = []
        for t in b["ticketed"]:
            bring.append(f"- Ticketed: [{t['name']}]({t['url']}) · {t['status']}")
        for r in b["owed_by_me"]:
            bring.append(f"- You owe: {r['text']} · [[{r['source']}]]")
        for r in b["owed_by_them"]:
            bring.append(f"- {r['owner']} owes: {r['text']} · [[{r['source']}]]")
        for q in b["open_questions"]:
            bring.append(f"- Open question last time: \"{q['quote']}\" · [[{q['note']}]]")
        out.append("**Bring**")
        out += bring or ["- Nothing tracked."]
        out.append("**Background**")
        if b["project"]:
            out.append(f"- [[{b['project']['page']}]]: {b['project']['state'] or 'no State block'}")
        if b["last"]:
            ago = b["last"]["weeks_ago"]
            when = "this week" if ago == 0 else f"{ago} week{'s' if ago != 1 else ''} ago"
            label = "Last time" if b["last"]["same_series"] else "Last with these people"
            out.append(f"- {label} ({when}): [[{b['last']['note']}]]. {b['last']['summary']}")
        else:
            out.append("- No earlier note with this title or these people.")
        for u in b["since_then"]:
            out.append(f"- Since then: {u}")
        prs = b.get("prs") or {}
        if prs.get("merged"):
            out.append("- Merged since then: " + " · ".join(f"[#{p['number']}]({p['url']}) {p['title'][:60]} ({p['author']})" for p in prs["merged"]))
        if prs.get("open"):
            out.append("- Open PRs: " + " · ".join(f"[#{p['number']}]({p['url']}) {p['title'][:60]} ({p['author']})" for p in prs["open"]))
        if b["came_from"]:
            c = b["came_from"][0]
            out.append(f"- Where this came from: [[{c['note']}]]: \"{_clean_md(c['quote'])}\"")
        if not b["last"] and b["body"]:
            out.append(f"- Invite: {b['body'][:200]}")
        out.append("")
    out += [f"_Generated {datetime.now(TZ).strftime('%H:%M')} by cos/prep.py; reads only._", BLOCK_END]
    return "\n".join(out)


def write_today(block):
    text = TODAY_NOTE.read_text(encoding="utf-8") if TODAY_NOTE.exists() else ""
    if BLOCK_START in text and BLOCK_END in text:
        a, b = text.index(BLOCK_START), text.index(BLOCK_END) + len(BLOCK_END)
        text = text[:a] + block + text[b:]
    else:
        text = text.rstrip("\n") + "\n\n" + block + "\n"
    TODAY_NOTE.write_text(text, encoding="utf-8")


def main(argv):
    day = date.today()
    as_json = "--json" in argv
    argv = [a for a in argv if a != "--json"]
    if "--date" in argv:
        i = argv.index("--date")
        day = date.fromisoformat(argv[i + 1])
        del argv[i:i + 2]
    selector = " ".join(argv).strip()
    errors = []
    try:
        events = fetch_events(day)
    except Exception as e:
        events, errors = [], [f"calendar: {e}"]
    # the block always covers the whole day; a selector only decides what gets printed
    if selector == "next":
        now = datetime.now(TZ).replace(tzinfo=None)
        picked = [e for e in events if datetime.fromisoformat(e["start_iso"]) >= now][:1]
    elif selector:
        picked = [e for e in events if selector.lower() in e["title"].lower()]
    else:
        picked = events
    idx = page_index()
    open_items = monday_open_items() if events else []
    briefs = [facts_for(e, day, idx, open_items) for e in events]
    shown = [b for b in briefs if b["id"] in {e["id"] for e in picked}]
    if as_json:
        print(json.dumps({"day": day.isoformat(), "found": len(shown), "errors": errors, "meetings": shown},
                         indent=1, ensure_ascii=False, default=str))
        return
    block = render(briefs, day, errors)
    if day != date.today():  # a past or future day is a preview, never today's note
        print(block)
        return
    write_today(block)
    if selector:
        print(render(shown, day, errors))
    print(f"prep: {len(briefs)} meeting(s) written to {TODAY_NOTE}" + (f"; errors: {errors}" if errors else ""))


if __name__ == "__main__":
    main(sys.argv[1:])
