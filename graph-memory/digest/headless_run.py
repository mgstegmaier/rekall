"""Write up one staged session with no window, then feed it to the index.

    python headless_run.py digest/pending/<session>.md
    python headless_run.py --drain    (reindex.sh, hourly: retry what failed before)

session_end.py spawns this detached in headless mode. It reads the staged text,
asks Claude for the entry, appends it to today's log inside your notes, then
distils that log file and rebuilds the index.

Nothing is thrown away on a failure. The staged file stays where it is and the
reason lands in digest/log/digest.log, so the next run can try again.
"""

import re
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))  # flat vendored layout, no rag/ subdir

import common  # noqa: E402
import distil  # noqa: E402


# session_end.py names each staged file <session id>-<YYYYmmdd-HHMMSS>.md, stamped when it closed
STAGED = re.compile(r"^(.+)-(\d{8}-\d{6})$")


def append(log, entry, when=None, session=""):
    """Add the entry under its own heading: the close time, then the session id's first 8
    characters, so two entries written in the same minute stay apart and a later entry can find
    this one. The log is only appended to."""
    when = when or datetime.now()
    tag = f" · {session[:8]}" if session else ""
    block = f"\n## Session {when:%H:%M}{tag}\n\n{entry.strip()}\n"
    with log.open("a", encoding="utf-8") as handle:
        handle.write(block)


HEX8 = re.compile(r"[0-9a-f]{8}")
BULLET = re.compile(r"^\s*- ")
ONLY_NEW = ("Decisions", "Facts", "Lessons", "Wins")  # dedupe runs here; Open loops is judged, not filtered
RECORDS = ONLY_NEW + ("Open loops",)  # a continuation needs a bullet under one of these


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


def payload(earlier, text):
    """What the model reads for a continuation: what is already recorded, then the transcript."""
    blocks = []
    for day, heading, body in earlier[:-1]:
        kept = [f"### {n}\n{section(body, n)}" for n in ("Decisions", "Open loops") if section(body, n)]
        if kept:
            blocks.append(f"[{day} {heading[8:13]}, earlier entry]\n" + "\n".join(kept))
    day, heading, body = earlier[-1]
    blocks.append(f"[{day} {heading[8:13]}, latest entry]\n{body}")
    return "Already recorded for this session:\n\n" + "\n\n".join(blocks) + "\n\n---\n\n" + text


def norm(bullet):
    """Lowercase, letters, digits and spaces only."""
    return " ".join("".join(c for c in bullet.lower() if c.isalnum() or c.isspace()).split())


def dedupe(entry, earlier):
    """Drop Decisions, Facts, Lessons and Wins bullets that repeat an earlier bullet for the
    session, and any of those headings left empty. A [monday ticket] bullet repeats only when its
    text is identical, so a status change stays. ponytail: a restatement in new words gets through."""
    old = [line for _, _, body in earlier for line in body.splitlines() if BULLET.match(line)]
    seen, raw = {norm(b) for b in old}, {b.strip() for b in old}
    out, held, gone, name = [], [], False, None  # held: the current heading and what is under it
    for line in entry.splitlines() + ["### "]:  # the sentinel flushes the last section
        if line.startswith("### "):
            if not (gone and not any(x.strip() for x in held[1:])):
                out += held
            held, gone, name = [line], False, line[4:].strip()
            continue
        if name in ONLY_NEW and BULLET.match(line):
            ticket = line.strip().startswith("- [monday ticket]")
            if (line.strip() in raw) if ticket else (norm(line) in seen):
                gone = True
                common.note_failure("headless_run", f"dropped a repeated {name} bullet: {line.strip()[:80]!r}")
                continue
        held.append(line)
    return "\n".join(out) + "\n"


def has_record(entry):
    """True when a bullet sits under Decisions, Facts, Lessons, Wins or Open loops."""
    return any(BULLET.match(line) for n in RECORDS for line in section(entry, n).splitlines())


def link_back(entry, latest, log_dir):
    """`Continues [[...]]` as the first line under ### What happened, which is added if missing.
    The folder prefix keeps a day file in daily-notes-archive from taking the link."""
    day, heading, _ = latest
    link = f"Continues [[{log_dir}/{day}#{heading}]]."
    head = re.search(r"^### What happened[ \t]*\n", entry, re.M)
    if head:
        return entry[: head.end()] + link + "\n" + entry[head.end() :]
    return f"### What happened\n{link}\n\n{entry}"


def drop(staged, why):
    """Out of pending/ for pending/dropped/, which drain() never reads; the text stays there in
    case the check was wrong."""
    dropped = staged.parent / "dropped"
    dropped.mkdir(exist_ok=True)
    staged.replace(dropped / staged.name)
    common.note_failure("headless_run", f"{staged.name}: moved to dropped/, {why}")
    common.note_failure("headless_run", f"digest dropped {why}")


def main(staged):
    cfg = common.config()
    notes = common.corpus()
    if notes is None:
        raise RuntimeError("no index yet, so there is nowhere for the entry to live")
    # the close time, not now: a drain that flushes a backlog would otherwise stamp every entry
    # with the flush time and file a session from yesterday under today
    m = STAGED.match(staged.stem)
    session, when = (m[1], datetime.strptime(m[2], "%Y%m%d-%H%M%S")) if m else ("", None)
    # a name that does not parse, or whose id is not a real session id, gets a first entry
    earlier = session_entries(notes / cfg["log_dir"], session[:8]) if HEX8.fullmatch(session[:8]) else []
    text = staged.read_text(encoding="utf-8")
    if not text.strip():
        staged.unlink(missing_ok=True)
        return
    text = payload(earlier, text) if earlier else text.replace(f"{common.NEW_MARKER}\n", "")

    entry = distil.ask(cfg["model"], common.PROMPT.read_text(encoding="utf-8"), text)
    if not entry.strip():
        raise RuntimeError("the model returned nothing")
    if entry.strip() == "THIN" or "### " not in entry:
        # filler, not an entry. A retry gets the same answer
        return drop(staged, f"the model wrote {entry.strip()[:80]!r}")
    if earlier:
        entry = dedupe(entry, earlier)
        if not has_record(entry):
            return drop(staged, "nothing new was left after the repeats came out")
        entry = link_back(entry, earlier[-1], cfg["log_dir"])
    log = common.today_log(notes, cfg, when=when)
    append(log, entry, when=when, session=session)
    staged.unlink(missing_ok=True)
    common.note_failure("headless_run", "digest ok")
    print(f"wrote {log}")

    if cfg["distil"]:
        # the entry reaches the index whether or not it distilled, because a
        # dropped distil still leaves a note that should be searchable
        distil.run(notes, paths=[log], rebuild=False)
        distil.rebuild_index(notes)


def drain(min_age=600):
    """Write up staged files older than min_age seconds, oldest first, one at a time. Younger
    ones may still have their own headless_run going. Stops at a sign-in failure, since every
    later file would fail the same way. ponytail: a file that always fails is retried each hour;
    its reason is in digest.log, and deleting it is the fix."""
    if common.config()["mode"] != "headless":
        return  # session mode leaves staged text for your next session on purpose
    for staged in sorted(common.PENDING.glob("*.md"), key=lambda p: p.stat().st_mtime):
        if time.time() - staged.stat().st_mtime < min_age:
            continue
        try:
            main(staged)
        except distil.NotSignedIn as exc:
            common.note_failure("drain", f"digest failed NotSignedIn {staged.name}: {exc}; stopping")
            return
        except Exception as exc:
            common.note_failure("drain", f"digest failed {type(exc).__name__} {staged.name}: {exc}")


if __name__ == "__main__":
    distil.utf8_out()
    if len(sys.argv) < 2:
        sys.exit("usage: python headless_run.py <staged file> | --drain")
    if sys.argv[1] == "--drain":
        drain()
        sys.exit(0)
    path = Path(sys.argv[1])
    try:
        main(path)
    except Exception as exc:
        common.note_failure("headless_run", f"digest failed {type(exc).__name__} {path.name}: {exc}")
        sys.exit(1)
