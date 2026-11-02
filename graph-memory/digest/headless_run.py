"""Write up one staged session with no window, then feed it to the index.

    python headless_run.py digest/pending/<session>.md
    python headless_run.py --drain    (reindex.sh, hourly: retry what failed before)

session_end.py spawns this detached in headless mode. It reads the staged text,
asks Claude for the entry, appends it to today's log inside your notes, then
distils that log file and rebuilds the index.

Nothing is thrown away on a failure. The staged file stays where it is and the
reason lands in digest/log/digest.log, so the next run can try again.
"""

import json
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
from rekall_config import STATE_DIR  # noqa: E402  (distil put the repo root on sys.path)


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


BULLET = re.compile(r"^\s*- ")
ONLY_NEW = ("Decisions", "Facts", "Lessons", "Wins")  # dedupe runs here; Open loops is judged, not filtered
RECORDS = ONLY_NEW + ("Open loops",)  # a continuation needs a bullet under one of these
section, session_entries, HEX8 = common.section, common.session_entries, common.HEX8


def payload(earlier, text, max_chars):
    """What the model reads for a continuation: what is already recorded, then the transcript,
    all of it at most max_chars. The recorded block gives way, never the transcript."""
    cap = min(max_chars // common.RECORDED_SHARE, max_chars - len(text))
    return common.recorded(earlier, cap) + text


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
        common.note_failure("headless_run", "digest dropped empty")
        return
    text = payload(earlier, text, cfg["max_chars"]) if earlier else text.replace(f"{common.NEW_MARKER}\n", "")

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
    print(f"wrote {log}")

    if cfg["distil"]:
        # the entry reaches the index whether or not it distilled, because a
        # dropped distil still leaves a note that should be searchable
        distil.run(notes, paths=[log], rebuild=False)
        distil.rebuild_index(notes)
    common.note_failure("headless_run", "digest ok")  # last, so a late distil error is the attempt's one tag


STRIKE_LIMIT = 3
STRIKES = STATE_DIR / "digest-strikes.json"  # staged file name -> consecutive non-auth failures


def drain(min_age=600):
    """Write up staged files older than min_age seconds, oldest first, one at a time. Younger
    ones may still have their own headless_run going. Stops at a sign-in failure, since every
    later file would fail the same way. A file whose claude call fails STRIKE_LIMIT times, in drains
    where another file succeeded (so not an outage, a timeout or a sign-in failure),
    moves to pending/failed/, which this never reads; the text stays there, the reasons are in
    digest.log, and moving it back retries it."""
    if common.config()["mode"] != "headless":
        return  # session mode leaves staged text for your next session on purpose
    try:
        strikes = json.loads(STRIKES.read_text(encoding="utf-8"))
    except Exception:
        strikes = {}
    done, failed = 0, []
    for staged in sorted(common.PENDING.glob("*.md"), key=lambda p: p.stat().st_mtime):
        if time.time() - staged.stat().st_mtime < min_age:
            continue
        try:
            main(staged)
            strikes.pop(staged.name, None)
            done += 1
        except distil.NotSignedIn as exc:
            common.note_failure("drain", f"digest failed NotSignedIn {staged.name}: {exc}; stopping")
            break
        except Exception as exc:
            common.note_failure("drain", f"digest failed {type(exc).__name__} {staged.name}: {exc}")
            # distil.run's rule: a timeout, a missing index or claude, is the machine's fault, no
            # strike; a failed call strikes only if another file in this drain got through
            if isinstance(exc, distil.ClaudeExit):
                failed.append(staged)
    for staged in failed if done else []:
        strikes[staged.name] = strikes.get(staged.name, 0) + 1
        if strikes[staged.name] >= STRIKE_LIMIT:  # not a second outcome tag: the attempt's line is above
            (staged.parent / "failed").mkdir(exist_ok=True)
            staged.replace(staged.parent / "failed" / staged.name)
            strikes.pop(staged.name)
            common.note_failure("drain", f"gave up on {staged.name} after {STRIKE_LIMIT} failures: now in pending/failed/")
    if not (strikes or STRIKES.exists()):
        return
    try:
        STRIKES.parent.mkdir(parents=True, exist_ok=True)
        STRIKES.write_text(json.dumps(strikes), encoding="utf-8")
    except OSError:
        pass  # a missing count only means one more retry


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
