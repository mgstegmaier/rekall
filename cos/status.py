#!/usr/bin/env python3
"""Friday status: the week's facts for a status update to your manager, from the wiki.

Five buckets, each {found, items}, every item carrying the reference it came from:
  shipped     Monday items marked Done this week, every `### Wins` bullet in this week's
              session digests, and this week's rows of the wins page's running log
              (deduplicated against the digest bullets by normalized text)
  in_flight   project pages with an `## Updates` entry dated this week: the entry's
              heading and its first sentence
  blocked     Monday items On Hold, with days on hold and the latest comment
  owed        open follow-ups ledger rows you own whose source note is a 1:1 with the
              audience named by [cos] status_audience in rekall.toml
  decisions   every `### Decisions` bullet in this week's digests, newest first, at most 10

The window is the last 7 days ending today. `--week-of YYYY-MM-DD` picks the Monday to
Sunday week holding that date and prints instead of writing, like prep.py's --date.

  status.py                          print the snapshot JSON (default)
  status.py render                   rewrite the <!-- cos-status --> block in today.md
  status.py [render] --week-of DATE  another week, printed, never written

Facts only. The /status skill turns the block into the Teams message. Reads the vault,
the ledger, and the Monday snapshot script named in rekall.toml; writes one marker block
into today.md and nothing else. Every source failure lands in errors[] with found 0 for
its bucket; a missing file is never an exception.
"""
import json
import re
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rekall_config import COS_GITHUB_ORGS, COS_MONDAY_SNAPSHOT, COS_STATUS_AUDIENCE, VAULT, WIKI  # noqa: E402

import followups  # ledger load() and bdays_between  # noqa: E402
import gh  # noqa: E402
import projects  # noqa: E402

SESSIONS = WIKI / "sessions"
PAGES = WIKI / "pages"
WINS_PAGE = PAGES / "annual-review-2026-accomplishments.md"  # the page wins-sweep.py appends to
AUDIENCE = COS_STATUS_AUDIENCE
GITHUB_ORGS = COS_GITHUB_ORGS
TODAY_NOTE = VAULT / "today.md"
BLOCK_START = "<!-- cos-status:start -->"
BLOCK_END = "<!-- cos-status:end -->"

DECISIONS_CAP = 10
WINDOW_DAYS = 7

RE_DATED_HEADING = re.compile(r"^### (\d{4}-\d{2}-\d{2})\s*(.*)$")
RE_LOG_ROW = re.compile(r"^- (\d{4}-\d{2}-\d{2}) (.*?)(?:\s*\(source: [^)]*\))?\s*$")


def norm(text):
    return re.sub(r"[^a-z0-9]", "", text.lower())


def in_window(d, start, end):
    return d is not None and start <= d <= end


def window(today, week_of=None):
    if week_of:
        start = week_of - timedelta(days=week_of.weekday())
        return start, start + timedelta(days=6)
    return today - timedelta(days=WINDOW_DAYS - 1), today


def first_sentence(lines):
    for line in lines:
        s = re.sub(r"\[([^\]]+)\]\(\S+\)", r"\1", line).strip()
        if s and not s.startswith("#"):
            return re.split(r"(?<=[.!?])\s", s, maxsplit=1)[0][:200]
    return ""


# ── sources ───────────────────────────────────────────────────

def digest_bullets(text, heading):
    """(session, bullet, context) for every `- ` line under `### heading` inside each `## Session HH:MM`.

    context is the first wikilinked page in that session's text before the bullet, which is how a
    digest names the project it worked on ("Quick pane layout tweak in [[herdr]]")."""
    out, session, sub, links = [], None, None, []
    for line in text.splitlines():
        if line.startswith("## "):
            session, sub, links = line[3:].strip(), None, []
            continue
        if line.startswith("### "):
            sub = line[4:].strip()
            continue
        if session:
            links += [l.strip() for l in re.findall(r"\[\[([^\]|#]+)", line) if l.strip() not in links]
        if sub == heading and line.startswith("- "):
            out.append((session, line[2:].strip(), list(links)))
    return out


def digests(start, end):
    """[(date, path, text)] for the digest files dated inside the window, oldest first."""
    out = []
    if not SESSIONS.is_dir():
        raise FileNotFoundError(f"{SESSIONS} is not a directory")
    for p in sorted(SESSIONS.glob("*.md")):
        m = re.match(r"(\d{4}-\d{2}-\d{2})", p.name)
        d = date.fromisoformat(m.group(1)) if m else None
        if in_window(d, start, end):
            out.append((d, p, p.read_text(encoding="utf-8", errors="replace")))
    return out


def digest_items(files, heading):
    return [{"text": b, "ref": f"{d.isoformat()} {s}", "file": p.name, "session": s, "context": c}
            for d, p, text in files for s, b, c in digest_bullets(text, heading)]


def wins_page_items(start, end):
    if not WINS_PAGE.exists():
        raise FileNotFoundError(f"{WINS_PAGE} does not exist")
    text = WINS_PAGE.read_text(encoding="utf-8", errors="replace")
    if "## Running log (auto)" not in text:
        return []
    out = []
    for line in text.split("## Running log (auto)", 1)[1].splitlines():
        if line.startswith("## "):
            break
        m = RE_LOG_ROW.match(line.strip())
        if m and in_window(date.fromisoformat(m.group(1)), start, end):
            out.append({"text": m.group(2), "ref": f"{m.group(1)} wins page", "file": WINS_PAGE.name})
    return out


def project_updates(start, end):
    if not PAGES.is_dir():
        raise FileNotFoundError(f"{PAGES} is not a directory")
    out = []
    for p in sorted(PAGES.glob("*.md")):
        text = p.read_text(encoding="utf-8", errors="replace")
        if not re.search(r"^type:\s*project\s*$", text[:1500], re.M) or "## Updates" not in text:
            continue
        lines = text.split("## Updates", 1)[1].splitlines()
        for i, line in enumerate(lines):
            if line.startswith("## "):
                break
            m = RE_DATED_HEADING.match(line)
            if not m or not in_window(date.fromisoformat(m.group(1)), start, end):
                continue
            body = []
            for nxt in lines[i + 1:]:
                if nxt.startswith("#"):
                    break
                body.append(nxt)
            heading, sentence = m.group(2).strip(" -—–"), first_sentence(body)
            out.append({"page": p.stem, "date": m.group(1), "heading": heading, "first_sentence": sentence,
                        "text": f"{heading}: {sentence}" if sentence else heading, "ref": f"{p.stem} {m.group(1)}"})
    out.sort(key=lambda u: (u["date"], u["page"]), reverse=True)
    # one line per project: the newest entry, with a count of the others this week (Mike, 2026-09-07)
    seen, collapsed = {}, []
    for u in out:
        if u["page"] in seen:
            seen[u["page"]]["more"] += 1
            continue
        u["more"] = 0
        seen[u["page"]] = u
        collapsed.append(u)
    for u in collapsed:
        if u["more"]:
            u["text"] += f" (+{u['more']} more update{'s' if u['more'] > 1 else ''} this week)"
    return collapsed


def monday():
    """(snapshot dict, error string). Runs the script named in rekall.toml; never raises."""
    if not COS_MONDAY_SNAPSHOT:
        return None, "no monday_snapshot in rekall.toml"
    try:
        r = subprocess.run([sys.executable, str(COS_MONDAY_SNAPSHOT)], capture_output=True, text=True, timeout=90,
                           stdin=subprocess.DEVNULL)
        snap = json.loads(r.stdout)
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"
    if snap.get("status") != "ok":
        return None, "; ".join(e.get("message", str(e)) for e in snap.get("errors", [])) or "snapshot blind"
    return snap, None


def wiki_project_text():
    """All project pages' text (the auto running log excluded: status.py writes there itself)."""
    if not PAGES.is_dir():
        raise FileNotFoundError(f"{PAGES} is not a directory")
    parts = []
    for p in PAGES.glob("*.md"):
        if p == WINS_PAGE:
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        if re.search(r"^type:\s*project\s*$", text[:1500], re.M):
            parts.append(text)
    return "\n".join(parts)


def pr_cited(pr, wiki_text):
    """A PR counts as cited when its URL appears, "PR #N" appears, or `#N` sits within 120 chars of its repo's short name."""
    if pr["url"] in wiki_text:
        return True
    repo = re.escape(pr.get("repo") or pr["project"])  # shipped items carry the repo as their project label
    n = pr["number"]
    # the wiki writes "PR #102 (merged ...)" as often as it names the repo; both count
    pat = r"\bPR #%d\b|\b%s\b.{0,120}#%d\b|#%d\b.{0,120}\b%s\b" % (n, repo, n, n, repo)
    return bool(re.search(pat, wiki_text, re.S))


def owed_rows(today):
    if not AUDIENCE.strip():
        raise ValueError("no status_audience in rekall.toml")
    words = AUDIENCE.lower().split()  # any word of the name in the filename counts
    out = []
    for r in followups.load()["rows"].values():
        name = Path(r["source"]).name.lower()
        if r["status"] != "open" or r["owner"] != "me" or "1-1" not in name or not any(w in name for w in words):
            continue
        opened = date.fromisoformat(r["opened"])
        out.append({"text": r["text"], "opened": r["opened"], "age_bdays": followups.bdays_between(opened, today),
                    "id": r["id"], "ref": Path(r["source"]).stem})
    return sorted(out, key=lambda r: r["opened"])


# ── snapshot ──────────────────────────────────────────────────

def snapshot(start, end, today):
    errors = []
    buckets = {k: [] for k in ("shipped", "in_flight", "blocked", "owed", "decisions", "unlinked")}

    def attempt(bucket, source, fn):
        try:
            return fn()
        except Exception as e:  # ponytail: any failure is a blind source, never a crash
            errors.append(f"{bucket}: {source}: {e}")
            return []

    snap, err = monday()
    if err:
        errors += [f"shipped: monday: {err}", f"blocked: monday: {err}"]
    else:
        for c in snap.get("done_this_week", []):
            if in_window(date.fromisoformat(c["completion_date"]), start, end):
                buckets["shipped"].append({"text": c["name"], "project": c.get("project"), "url": c.get("url"),
                                           "date": c["completion_date"], "ref": f"Monday {c['completion_date']}"})
        for c in snap.get("on_hold", []):
            buckets["blocked"].append({"text": c["name"], "project": c.get("project"), "url": c.get("url"),
                                       "days_on_hold": c.get("business_days_idle"), "last_comment": c.get("last_comment"),
                                       "ref": f"Monday, {c.get('business_days_idle', '?')}bd on hold"})

    # GitHub: merged PRs are the authoritative Shipped for the audience; open ones are In flight or Blocked.
    # A PR is labelled by the wiki project whose `repos:` covers it, else by its repo.
    mapping = attempt("shipped", "project repos", lambda: projects.project_repos()) or {}

    def pr_item(pr, ref):
        page, candidates = projects.project_for(pr["full_repo"], gh.pr_files(pr["url"]) if mapping else [], mapping)
        return {"text": pr["title"], "project": page_title(page) if page else pr["repo"], "repo": pr["repo"],
                "page": page, "candidates": candidates, "number": pr["number"], "url": pr["url"],
                "date": pr.get("date"), "ref": f"{pr['repo']} {ref}"}

    for pr in attempt("shipped", "github", lambda: gh.merged_prs(start, GITHUB_ORGS)):
        if in_window(date.fromisoformat(pr["date"]), start, end):
            buckets["shipped"].append(pr_item(pr, f"PR merged {pr['date']}"))
    open_prs = attempt("in_flight", "github", lambda: gh.open_prs(GITHUB_ORGS, today))
    stuck = gh.waiting(open_prs)
    for pr in open_prs:
        if pr in stuck:
            buckets["blocked"].append(pr_item(pr, f"PR, {pr['wait_bdays']}bd without approval, {pr['review'].lower().replace('_', ' ')}"))
        else:
            buckets["in_flight"].append(pr_item(pr, f"PR open since {pr['opened']}"))
    for pr in attempt("owed", "github", lambda: gh.review_requests(GITHUB_ORGS)):
        buckets["owed"].append(pr_item(pr, f"PR review requested by {pr['author']}"))

    # Rigor: every merged PR should be cited on a wiki project page and logged on a Monday ticket
    ticketed_urls = set()
    if not err:
        for c in snap.get("open_items", []) + snap.get("done_this_week", []):
            ticketed_urls.update(c.get("pr_urls", []))
    wiki_text = attempt("unlinked", "project pages", lambda: wiki_project_text())
    for pr in [b for b in buckets["shipped"] if b.get("number")]:
        missing = []
        if wiki_text and not pr_cited(pr, wiki_text):  # attempt() gives [] when pages are unreadable
            if pr.get("page"):
                missing.append(f"cite on {pr['page']}")
            elif pr.get("candidates"):
                missing.append("cite on one of " + ", ".join(pr["candidates"]))
            else:
                missing.append("wiki page")
        if not err and pr["url"] not in ticketed_urls:
            missing.append("Monday ticket")
        if missing:
            buckets["unlinked"].append({**pr, "missing": missing, "ref": "missing: " + ", ".join(missing)})

    files = attempt("shipped", "digests", lambda: digests(start, end))
    wins = digest_items(files, "Wins")
    buckets["shipped"] += wins
    seen = {norm(w["text"]) for w in wins}
    for w in attempt("shipped", "wins page", lambda: wins_page_items(start, end)):
        if norm(w["text"]) not in seen:
            buckets["shipped"].append(w)
            seen.add(norm(w["text"]))
    buckets["in_flight"] += attempt("in_flight", "project pages", lambda: project_updates(start, end))
    buckets["owed"] += attempt("owed", "ledger", lambda: owed_rows(today))
    decisions = digest_items(files, "Decisions")
    buckets["decisions"] = list(reversed(decisions))[:DECISIONS_CAP]

    out = {
        "generated": datetime.now().isoformat(timespec="seconds"),
        "status": "blind" if errors and not any(buckets.values()) else "ok",
        "errors": errors,
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "audience": AUDIENCE,
    }
    out.update({k: {"found": len(v), "items": v} for k, v in buckets.items()})
    return out


# ── render ────────────────────────────────────────────────────

# Shipped last: the open work is what Mike reads first (Mike, 2026-09-07)
HEADINGS = [("in_flight", "In flight"), ("blocked", "Blocked"), ("owed", "You owe"),
            ("decisions", "Decisions this week"), ("unlinked", "PRs not linked"), ("shipped", "Shipped")]
WINS_HEADING = "## Running log (auto)"


_TITLE_CACHE = {}


def page_title(stem):
    """Display name for a wiki page: frontmatter title, else H1, else the stem. Cached."""
    if stem in _TITLE_CACHE:
        return _TITLE_CACHE[stem]
    name = stem.replace("-", " ")
    path = PAGES / f"{stem}.md"
    if path.exists():
        text = path.read_text(encoding="utf-8", errors="replace")
        fm = text.split("---", 2)[1] if text.startswith("---") else ""
        m = re.search(r'^title:\s*"?(.+?)"?\s*$', fm, re.M) or re.search(r"^# (.+)$", text, re.M)
        if m:
            name = m.group(1).strip()
    _TITLE_CACHE[stem] = name
    return name


_PAGES = None


def pages_index():
    """{'project': {stem: significant words}, 'person': {stems}} from wiki/pages frontmatter."""
    global _PAGES
    if _PAGES is None:
        _PAGES = {"project": {}, "person": set(), "alias": {}}
        for path in PAGES.glob("*.md"):
            text = path.read_text(encoding="utf-8", errors="replace")
            fm = text.split("---", 2)[1] if text.startswith("---") else ""
            t = re.search(r"^type:\s*(\w+)", fm, re.M)
            if not t:
                continue
            for a in re.findall(r"^\s+-\s+(.+)$", re.search(r"^aliases:\s*\n((?:[ \t]+-\s+.+\n?)+)", fm, re.M).group(1), re.M) \
                    if re.search(r"^aliases:\s*\n", fm, re.M) else []:
                _PAGES["alias"][re.sub(r"[^a-z0-9]", "", a.lower())] = path.stem
            _PAGES["alias"].setdefault(re.sub(r"[^a-z0-9]", "", path.stem.lower()), path.stem)
            if t.group(1) == "person":
                _PAGES["person"].add(path.stem)
            elif t.group(1) == "project":
                names = [page_title(path.stem), path.stem.replace("-", " ")]
                m = re.search(r"^aliases:\s*\n((?:[ \t]+-\s+.+\n?)+)", fm, re.M)
                if m:
                    names += re.findall(r"-\s+(.+)", m.group(1))
                _PAGES["project"][path.stem] = sig_words(" ".join(names))
    return _PAGES


STOP = {"meeting", "call", "sync", "weekly", "daily", "standup", "review", "with", "and", "the", "team", "project",
        "update", "data", "platform", "pipeline", "pipelines", "refactor", "automation", "integration"}


def sig_words(text):
    return {w for w in re.sub(r"[^a-z0-9 ]", " ", text.lower()).split() if len(w) >= 3 and w not in STOP}


def resolve_stem(link):
    """A wikilink target as a real page stem: exact file, else alias or squashed-name match."""
    if (PAGES / f"{link}.md").exists():
        return link
    return pages_index()["alias"].get(re.sub(r"[^a-z0-9]", "", link.lower()), link)


def project_by_words(text):
    """The project page whose name shares the most words with the text: 2 shared, or 1 when the
    page name is one or two words (QVal, Rekall). None when nothing clears the bar."""
    words = sig_words(text)
    best, score = None, 0
    for stem, names in pages_index()["project"].items():
        shared = len(words & names)
        if shared > score and (shared >= 2 or (shared == 1 and len(names) == 1)):
            best, score = stem, shared
    return best


def label_for(key, it):
    """The project, system, or meeting a line belongs to, recognisable at a glance."""
    if it.get("project"):  # Monday items carry the board's Project label; PRs carry their repo
        return it["project"]
    if key == "in_flight":
        return page_title(it["page"])
    if key == "owed":
        return f"1:1 {(AUDIENCE.split() or ['manager'])[0]}"
    m = re.search(r"\[\[([^\]|#]+)", it.get("text", ""))  # first wikilink in a digest bullet
    if m:
        return page_title(resolve_stem(m.group(1).strip()))
    idx = pages_index()
    links = [resolve_stem(l) for l in it.get("context") or []]
    for l in links:  # the session's own links: first project page, else first non-person page
        if l in idx["project"]:
            return page_title(l)
    for l in links:
        if l and l not in idx["person"]:
            return page_title(l)
    stem = project_by_words(it.get("text", ""))  # last resort: the bullet names the project itself
    if stem:
        return page_title(stem)
    return "Session" if "session" in it else "Wins page"


def line_text(key, it, label):
    if key == "in_flight":
        text = it.get("heading") or it["text"]
        if it.get("more"):
            text += f" (+{it['more']} more)"
        return text
    text = it["text"]
    # a digest bullet that opens with the same page link the label already names: drop the prefix
    text = re.sub(r"^\[\[[^\]]+\]\]\s*(\([^)]*\))?\s*:\s*", "", text)
    return text[:160].rstrip() + ("…" if len(text) > 160 else "")


def render_block(snap):
    who = (snap["audience"].split() or ["your manager"])[0]
    w = snap["window"]
    out = [BLOCK_START, f"## Status · {w['start']} to {w['end']}", ""]
    for key, title in HEADINGS:
        b = snap[key]
        out.append(f"**{title.format(who=who)} ({b['found']})**")
        for e in snap["errors"]:
            bucket, source, reason = e.split(": ", 2)
            if bucket == key:
                out.append(f"{source} is blind: {reason}")
        labelled = [(label_for(key, it), it) for it in b["items"]]
        labelled.sort(key=lambda t: (t[0].lower() in ("session", "wins page"), t[0].lower()))  # cluster by project, loose ones last
        for label, it in labelled:
            extra = f" · {it['age_bdays']}bd" if "age_bdays" in it else ""
            num = f"[#{it['number']}]({it['url']}) " if it.get("number") else ""
            out.append(f"- **{label}** · {num}{line_text(key, it, label)}{extra} [{it['ref']}]")
        out.append("")
    out += [FOOTER, BLOCK_END]
    return "\n".join(out)


def append_running_log(snap):
    """Add this week's Monday Done items to the wins page's running log, labelled by project, once.

    Digest wins already reach that log through scripts/wins-sweep.py; this covers the ticketed work
    the digests never saw. Dedupe is by normalized text against every bullet already on the page."""
    if not WINS_PAGE.exists():
        return 0
    text = WINS_PAGE.read_text(encoding="utf-8")
    if WINS_HEADING not in text:
        return 0
    have = {re.sub(r"[^a-z0-9]", "", line.lower()) for line in text.splitlines() if line.startswith("- ")}
    new = []
    for it in snap["shipped"]["items"]:
        if not it.get("project"):  # Monday items only; digest and wins-page rows are already there
            continue
        key = re.sub(r"[^a-z0-9]", "", it["text"].lower())
        if any(key and key in h for h in have):
            continue
        what = f"#{it['number']} {it['text']}" if it.get("number") else it["text"]
        src = f"PR {it['url']}" if it.get("number") else f"Monday {it.get('url', '')}"
        new.append(f"- {it['date']} **{it['project']}** · {what} (source: {src})".rstrip())
    if new:
        WINS_PAGE.write_text(text.rstrip("\n") + "\n" + "\n".join(new) + "\n", encoding="utf-8")
    return len(new)


FOOTER = "_Facts by cos/status.py · draft the message with /status_"


def write_today(block):
    """Replace the block, keeping any **Draft** section the skill or Mike wrote under the facts."""
    text = TODAY_NOTE.read_text(encoding="utf-8") if TODAY_NOTE.exists() else ""
    if BLOCK_START in text and BLOCK_END in text:
        a, b = text.index(BLOCK_START), text.index(BLOCK_END) + len(BLOCK_END)
        old = text[a:b]
        if "**Draft**" in old and FOOTER in old and FOOTER in block:
            draft = old[old.index("**Draft**"):old.index(FOOTER)]
            block = block.replace(FOOTER, draft + FOOTER)
        text = text[:a] + block + text[b:]
    else:
        text = text.rstrip("\n") + "\n\n" + block + "\n"
    TODAY_NOTE.write_text(text, encoding="utf-8")


def main(argv):
    today = date.today()
    week_of = None
    if "--week-of" in argv:
        i = argv.index("--week-of")
        week_of = date.fromisoformat(argv[i + 1])
        del argv[i:i + 2]
    verb = argv[0] if argv else "snapshot"
    start, end = window(today, week_of)
    snap = snapshot(start, end, today)
    if verb != "render":
        print(json.dumps(snap, indent=1, ensure_ascii=False))
        return
    block = render_block(snap)
    if week_of:  # another week is a preview, never today's note
        print(block)
        return
    write_today(block)
    added = append_running_log(snap)
    print(f"wrote status block to {TODAY_NOTE}" + (f"; errors: {snap['errors']}" if snap["errors"] else "")
          + (f" · {added} shipped item(s) added to the running log" if added else ""))


if __name__ == "__main__":
    main(sys.argv[1:])
