"""SessionEnd hook: log recall use, filter the session, then stage or spawn.

Code does the filtering, so nothing is judged out by mistake. What survives is
your words and the replies. Tool calls, results, file dumps, thinking and
anything this file does not recognise are dropped.

Then the mode in config.json decides who writes the entry:

    headless   spawn headless_run.py detached and get out of the way
    session    leave the text staged for your next session to write up

This hook returns in well under a second and always exits 0. A session is
never held up by its own memory.
"""

import glob
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import common  # noqa: E402
import recall_use  # noqa: E402
from harness_prompt import INJECTED, REMINDER  # noqa: E402  (common put graph-memory/ on sys.path)


def read_stdin():
    """The hook payload. Windows can hand us lone backslashes in a path."""
    raw = sys.stdin.read()
    try:
        return json.loads(raw)
    except ValueError:
        return json.loads(re.sub(r'(?<!\\)\\(?!["\\])', r"\\\\", raw))


def turns(transcript):
    """The conversation out of the transcript, in order, as (who, text, timestamp or None).
    Default is to drop."""
    kept = []
    with Path(transcript).open(encoding="utf-8", errors="replace") as handle:
        for raw in handle:
            line = raw.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if not isinstance(event, dict):
                continue
            if event.get("isSidechain") is True:  # a sub agent's own talk
                continue
            if event.get("type") not in ("user", "assistant"):
                continue
            if event.get("toolUseResult") is not None:  # a tool result carrier
                continue
            if event.get("isMeta") is True or event.get("isCompactSummary") is True:
                continue
            message = event.get("message")
            if not isinstance(message, dict):
                continue
            role = message.get("role")
            if role not in ("user", "assistant"):
                continue
            body = common.text_blocks(message.get("content")).strip()
            if role == "user":
                body = REMINDER.sub("", body).strip()
                if body.startswith(INJECTED):
                    continue
            if not body:
                continue
            kept.append(("You" if role == "user" else "Claude", body, event.get("timestamp")))
    return kept


def local(when):
    """A transcript timestamp as naive local time, the clock the staged file names use."""
    return datetime.fromisoformat(when.replace("Z", "+00:00")).astimezone().replace(tzinfo=None)


def filtered(transcript, cfg, since=None, budget=None):
    """The whole conversation when it fits budget (default max_chars), marker included. Otherwise
    the opening quarter of the budget, where the session's goal was said, then as much of the end as fits, cut at whole turns. When
    since is the time of an earlier close, common.NEW_MARKER goes before the first kept turn
    newer than it."""
    kept = turns(transcript)
    if len(kept) < cfg["min_turns"]:
        return None
    budget = cfg["max_chars"] if budget is None else budget
    blocks = [f"**{who}:** {body}" for who, body, _ in kept]
    new = next((i for i, (_, _, when) in enumerate(kept) if since and when and local(when) > since), None)
    if new is not None:
        budget -= len(common.NEW_MARKER) + 1  # the marker and its newline count against the budget
    if len("\n\n".join(blocks)) <= budget:
        if new is not None:
            blocks[new] = f"{common.NEW_MARKER}\n{blocks[new]}"
        return "\n\n".join(blocks)
    budget -= 40  # room for the omitted marker
    if budget < 40:  # no room for even one turn
        return None
    # ponytail: one turn longer than a quarter of the budget (a pasted file, say) is clipped, so
    # the head and the tail each keep at least one whole turn
    blocks = [b if len(b) <= budget // 4 else b[: budget // 4 - 6] + " [...]" for b in blocks]
    head, used = [], 0
    for block in blocks:
        if used + len(block) > budget // 4:
            break
        head.append(block)
        used += len(block) + 2
    tail = []
    for block in reversed(blocks[len(head) :]):
        if used + len(block) > budget:
            break
        tail.insert(0, block)
        used += len(block) + 2
    omitted = len(blocks) - len(head) - len(tail)
    if new is not None:
        new = new if new < len(head) or new >= len(blocks) - len(tail) else len(blocks) - len(tail)
        if new < len(blocks):
            blocks[new] = f"{common.NEW_MARKER}\n{blocks[new]}"
        head, tail = blocks[: len(head)], blocks[len(blocks) - len(tail) :]
    return "\n\n".join(head + [f"[... {omitted} turns omitted ...]"] + tail)


CLOSED = re.compile(r"-(\d{8}-\d{6})\.(?:md|out)$")


def last_close(safe):
    """When this session last closed, as naive local time, or None. The earlier close is the
    newest <safe>-<stamp> file: the .out log a write-up leaves, or a staged file still waiting in
    pending/ or set aside in pending/dropped/."""
    names = [p.name for folder in (common.LOG, common.PENDING, common.PENDING / "dropped")
             for p in folder.glob(f"{glob.escape(safe)}-*")]
    stamps = [m[1] for m in map(CLOSED.search, names) if m]
    return datetime.strptime(max(stamps), "%Y%m%d-%H%M%S") if stamps else None


def typed_since_last_close(transcript, safe):
    """False when this session closed before and nothing was typed since. A reopened session
    that is closed again without a new prompt would otherwise be written up a second time. The
    earlier close is last_close(safe)."""
    last = last_close(safe)
    if not last:
        return True
    for who, _, when in turns(transcript):
        if who == "You" and when:
            if local(when) > last:
                return True
    return False


def spawn(staged):
    """Run the write up detached, so closing the session does not wait on it."""
    common.LOG.mkdir(parents=True, exist_ok=True)
    handle = (common.LOG / f"{staged.stem}.out").open("ab")
    extra = {}
    if os.name == "nt":
        extra["creationflags"] = (
            subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        )
    else:
        extra["start_new_session"] = True
    subprocess.Popen(
        # -u so the log fills as it goes, not only when the run finishes
        [sys.executable, "-u", str(HERE / "headless_run.py"), str(staged)],
        stdin=subprocess.DEVNULL,
        stdout=handle,
        stderr=handle,
        close_fds=True,
        **extra,
    )


def monday_line(session_id):
    """Join the session to its Monday ticket by session id (state written by the monday-nudge
    hook / monday_ticket.py in familiar). Deterministic; the digest never parses URLs out of prose."""
    # the monday plugin writes ~/.config/ucg-claude/monday (or $MONDAY_STATE_DIR); the two older
    # dirs are the familiar-repo copy and the pre-2026-09 rekall location
    dirs = [Path(os.environ.get("MONDAY_STATE_DIR") or Path.home() / ".config" / "ucg-claude" / "monday"),
            Path.home() / ".config" / "familiar" / "monday", Path.home() / ".config" / "rekall" / "monday"]
    st = {}
    for d in dirs:
        try:
            st = json.loads((d / f"{session_id}.json").read_text())
            break
        except Exception:
            continue
    if not st.get("item_id"):
        return ""
    status = f'closed {st["closed_status"]}' if st.get("closed_at") else "open"
    return f'[monday ticket] #{st["item_id"]} "{st.get("name", "")}" {st.get("url", "")} ({status})\n\n'


def main():
    if os.environ.get("MEMORY_STARTER_CHILD"):  # our own headless call closing
        return
    if os.environ.get("REKALL_NO_DIGEST"):  # headless chief-of-staff runs leave no durable memory (Mike, 2026-09-07)
        return
    try:
        payload = read_stdin()
    except Exception:
        return
    transcript = payload.get("transcript_path") or ""
    session_id = str(payload.get("session_id") or "session")
    if not transcript or not Path(transcript).is_file():
        return
    recall_use.log(transcript, session_id)

    cfg = common.config()
    notes = common.corpus()
    if notes is None:  # no index yet, so nowhere for an entry to live
        return
    safe = re.sub(r"[^A-Za-z0-9_-]+", "-", session_id)[:64] or "session"
    try:
        if not typed_since_last_close(transcript, safe):
            return
        # a continuation sends the already-recorded block ahead of this text (headless_run.payload),
        # so the Monday line and that block come off the budget first
        monday = monday_line(session_id)
        earlier = common.session_entries(notes / cfg["log_dir"], safe[:8]) if common.HEX8.fullmatch(safe[:8]) else []
        room = cfg["max_chars"] - len(monday) - len(common.recorded(earlier, cfg["max_chars"] // common.RECORDED_SHARE))
        text = filtered(transcript, cfg, last_close(safe), budget=room)
    except Exception as exc:
        common.note_failure("session_end", f"{type(exc).__name__} {exc}")
        return
    if not text:
        return
    text = monday + text

    # the stamp matters: one session can close more than once, and neither
    # write-up may overwrite the other
    common.PENDING.mkdir(parents=True, exist_ok=True)
    staged = common.PENDING / f"{safe}-{datetime.now():%Y%m%d-%H%M%S}.md"
    staged.write_text(text, encoding="utf-8")

    if cfg["mode"] == "headless":
        try:
            spawn(staged)
        except Exception as exc:
            common.note_failure("session_end", f"spawn: {type(exc).__name__} {exc}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # a session close is never blocked by this
        common.note_failure("session_end", f"{type(exc).__name__} {exc}")
    sys.exit(0)
