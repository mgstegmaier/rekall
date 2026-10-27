"""Write up one staged session with no window, then feed it to the index.

    python headless_run.py digest/pending/<session>.md
    python headless_run.py --drain    (reindex.sh, hourly: retry what failed before)

session_end.py spawns this detached in headless mode. It reads the staged text,
asks Claude for the entry, appends it to today's log inside your notes, then
distils that log file and rebuilds the index.

Nothing is thrown away on a failure. The staged file stays where it is and the
reason lands in digest/log/digest.log, so the next run can try again.
"""

import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))  # flat vendored layout, no rag/ subdir

import common  # noqa: E402
import distil  # noqa: E402


def append(log, entry, when=None):
    """Add the entry under its own time heading. The log is only appended to."""
    when = when or datetime.now()
    block = f"\n## Session {when:%H:%M}\n\n{entry.strip()}\n"
    with log.open("a", encoding="utf-8") as handle:
        handle.write(block)


def main(staged):
    cfg = common.config()
    notes = common.corpus()
    if notes is None:
        raise RuntimeError("no index yet, so there is nowhere for the entry to live")
    text = staged.read_text(encoding="utf-8")
    if not text.strip():
        staged.unlink(missing_ok=True)
        return

    entry = distil.ask(cfg["model"], common.PROMPT.read_text(encoding="utf-8"), text)
    if not entry.strip():
        raise RuntimeError("the model returned nothing")

    log = common.today_log(notes, cfg)
    append(log, entry)
    staged.unlink(missing_ok=True)
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
            common.note_failure("drain", f"{staged.name}: {exc}; stopping")
            return
        except Exception as exc:
            common.note_failure("drain", f"{staged.name}: {type(exc).__name__} {exc}")


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
        common.note_failure("headless_run", f"{path.name}: {type(exc).__name__} {exc}")
        sys.exit(1)
