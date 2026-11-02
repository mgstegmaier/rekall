"""The recall-use log: each recall-hook injection in a session, the event that triggered it, and
per label whether the session Read that file or reused the excerpt within the injection's window.

session_end.main() calls log() at every close; a resumed session closes again and appends again,
so readers keep the last line per session. Run as a script:

    python3 graph-memory/digest/recall_use.py --show <transcript>   print scan() of a transcript
    python3 graph-memory/digest/recall_use.py --rebuild             regenerate v1 lines (no "v")

The line format, the trigger walk and the window are described in graph-memory/README.md.
"""

import glob
import json
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import common  # noqa: E402  (puts graph-memory/ on sys.path)
from harness_prompt import REMINDER  # noqa: E402
from hook_format import parse  # noqa: E402

COMPANION = ("[Image: source:", "Base directory for this skill")
LOG_NAME = "recall-use.jsonl"
BACKUP_NAME = "recall-use.v1-backup.jsonl"


def _text(content):
    """A trigger's text: reminder blocks stripped before the cut, so none is left unterminated."""
    return REMINDER.sub("", common.text_blocks(content)).strip()[:200]


def _kind(event):
    """What an event is to the trigger walk."""
    kind = event.get("type")
    if kind == "assistant":
        return "assistant"
    if kind == "attachment":
        return "queued" if (event.get("attachment") or {}).get("type") == "queued_command" else "pass"
    if kind != "user":
        return "pass"  # system events, and anything else on the chain
    if event.get("toolUseResult") is not None:
        return "tool"
    if event.get("isCompactSummary"):
        return "compact"
    if event.get("isMeta"):
        text = common.text_blocks((event.get("message") or {}).get("content")).lstrip()
        return "companion" if text.startswith(COMPANION) else "meta"
    return "typed"


def _trigger(recs, start):
    """(kind, uuid, text, origin) of the event that triggered an injection, or all None."""
    cur, seen = start, set()
    while cur and cur not in seen and cur in recs:
        seen.add(cur)
        kind, parent, text, origin = recs[cur]
        if kind in ("typed", "meta", "queued"):
            return kind, cur, text, origin
        if kind not in ("pass", "companion"):  # assistant, tool result, compact summary
            break
        cur = parent
    return None, None, None, None


def _rekall_items(attachment):
    """The hook's items in a UserPromptSubmit additional-context attachment, else []."""
    if attachment.get("type") != "hook_additional_context" or attachment.get("hookEvent") != "UserPromptSubmit":
        return []
    content = attachment.get("content")
    return parse("\n\n".join(map(str, content if isinstance(content, list) else [content or ""])))


def scan(transcript):
    """Every rekall injection in the transcript, in order, in one pass."""
    recs, injections, open_ = {}, [], []
    with Path(transcript).open(encoding="utf-8", errors="replace") as handle:
        for raw in handle:
            try:
                event = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(event, dict) or event.get("isSidechain") is True:
                continue
            kind, uuid = _kind(event), event.get("uuid")
            parent = event.get("parentUuid") or event.get("logicalParentUuid")  # null after a compaction
            message = event.get("message") if isinstance(event.get("message"), dict) else {}
            if kind in ("typed", "meta"):
                open_ = []  # a new prompt ends every open window
                recs[uuid] = (kind, parent, _text(message.get("content")), None)
                continue
            attachment = event.get("attachment") if isinstance(event.get("attachment"), dict) else {}
            if kind == "queued":  # doesn't end a window: it mostly arrives while Claude is mid-task
                recs[uuid] = (kind, parent, _text(attachment.get("prompt")), (attachment.get("origin") or {}).get("kind"))
                continue
            recs[uuid] = (kind, parent, None, None)
            found = _rekall_items(attachment) if attachment else []
            if found:
                trig, trig_uuid, prompt, origin = _trigger(recs, parent)
                labels, graph = [], {}
                for item_kind, label, excerpt, _ in found:
                    if item_kind == "graph":
                        graph.setdefault(label, {"doc": label, "read": False})
                        continue
                    file, section = label.split(" § ", 1)
                    # ponytail: "rarest" = the 5 longest distinct words; df from rag.db is the
                    # upgrade if this proves noisy
                    words = dict.fromkeys(re.findall(r"\w{4,}", excerpt.lower()))
                    labels.append({"file": file, "section": section, "read": False, "reused": False,
                                   "_terms": sorted(words, key=len, reverse=True)[:5]})
                inj = {"attachment_uuid": uuid, "trigger_uuid": trig_uuid, "trigger": trig, "origin": origin,
                       "prompt": prompt, "labels": labels, "graph": list(graph.values())}
                injections.append(inj)
                open_.append(inj)
                continue
            if kind != "assistant" or not open_:
                continue
            content = message.get("content") if isinstance(message.get("content"), list) else []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("name") == "Read":
                    path = str((block.get("input") or {}).get("file_path", "")).replace("\\", "/")
                    for inj in open_:
                        for label in inj["labels"]:
                            label["read"] |= path.endswith("/" + label["file"])
                        for doc in inj["graph"]:
                            doc["read"] |= path.endswith("/" + doc["doc"])
            reply = common.text_blocks(content).lower()
            for inj in open_:
                for label in inj["labels"]:
                    label["reused"] |= sum(t in reply for t in label["_terms"]) >= 2
    for inj in injections:
        for label in inj["labels"]:
            del label["_terms"]
    return injections


def line(session_id, injections, ts=None, rebuilt=False):
    """One session close as a v2 log line."""
    row = {"v": 2, "session": session_id, "ts": ts or datetime.now().isoformat(timespec="seconds"),
           "injections": injections}
    if rebuilt:
        row["rebuilt"] = True
    return row


def append(line_dict):
    """One os.write with O_APPEND, no lock. Failures go to digest.log."""
    # ponytail: O_APPEND keeps concurrent whole-line writes intact on macOS and Linux local disks
    # only. Windows emulates it as seek+write and a network drive promises nothing, so two closes
    # at once can clobber there. About 75 MB a year, never rotated. One file per session
    # (recall-use/<session>.json via os.replace) is the upgrade if a line is ever lost.
    data = (json.dumps(line_dict) + "\n").encode("utf-8")
    try:
        common.LOG.mkdir(parents=True, exist_ok=True)
        fd = os.open(common.LOG / LOG_NAME, os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_BINARY", 0), 0o644)
        try:
            n = os.write(fd, data)
        finally:
            os.close(fd)
        if n < len(data):
            common.note_failure("recall_use", f"short write: {n} of {len(data)} bytes")
    except Exception as exc:
        common.note_failure("recall_use", f"{type(exc).__name__} {exc}")


def log(transcript, session_id):
    """Scan the transcript and append its line. A session with no injections writes none. Never raises."""
    try:
        injections = scan(transcript)
        if injections:
            append(line(session_id, injections))
    except Exception as exc:
        common.note_failure("recall_use", f"{type(exc).__name__} {exc}")


def find_transcript(session_id):
    """The newest <config dir>/projects/*/<session>.jsonl by mtime, or None."""
    root = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    found = [Path(p) for p in glob.glob(str(root / "projects" / "*" / f"{glob.escape(session_id)}.jsonl"))]
    return max(found, key=lambda p: p.stat().st_mtime) if found else None


def _last_lines(path):
    """The last parseable line per session, in order of each session's first line."""
    last = {}
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            row = json.loads(raw)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("session"):
            last[row["session"]] = row
    return last


def rebuild():
    """Append a v2 line for every session whose last line is v1. Safe to run again. Exit code."""
    live = common.LOG / LOG_NAME
    if not live.exists():
        print("nothing to rebuild")
        return 0
    backup = common.LOG / BACKUP_NAME
    if not backup.exists():
        shutil.copy2(live, backup)
    counts = dict.fromkeys(("rebuilt", "already v2", "missing", "empty", "failed"), 0)
    for session, row in _last_lines(live).items():
        if "v" in row:
            counts["already v2"] += 1
            continue
        transcript = find_transcript(session)
        if transcript is None:
            counts["missing"] += 1
            continue
        try:
            injections = scan(transcript)
        except Exception as exc:
            common.note_failure("recall_use", f"rebuild {session}: {type(exc).__name__} {exc}")
            counts["failed"] += 1
            continue
        if not injections:
            counts["empty"] += 1
            continue
        if "v" in _last_lines(live).get(session, {}):  # the session closed again meanwhile
            counts["already v2"] += 1
            continue
        append(line(session, injections, ts=row.get("ts"), rebuilt=True))
        counts["rebuilt"] += 1
    print(", ".join(f"{k} {n}" for k, n in counts.items()))
    return 1 if counts["failed"] else 0


def main(argv):
    if argv == ["--rebuild"]:
        sys.exit(rebuild())
    if len(argv) == 2 and argv[0] == "--show":
        print(json.dumps(scan(argv[1]), indent=1))
        return
    print("usage: recall_use.py --rebuild | --show <transcript>", file=sys.stderr)
    sys.exit(2)


if __name__ == "__main__":
    main(sys.argv[1:])
