"""headless_run.main: a session that already has an entry gets a continuation. The model reads what
is recorded, then the transcript; code drops repeated bullets, drops an entry with nothing left,
and writes the backlink. A first entry, or a name that is no session id, is written as before.
Run: python graph-memory/test_digest_continuation.py"""
import importlib
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "digest"))
import headless_run  # noqa: E402

headless_run = importlib.reload(headless_run)  # test_digest_drain stubs main() in the shared pytest process
common, distil = headless_run.common, headless_run.distil
real = distil.ask, common.corpus, common.config, common.PENDING, common.LOG, headless_run.session_entries

OLD = """### What happened
Wired the build.

### Decisions
- Use Sonnet for digests
- Keep the opening

### Facts
- Budget is 40,000 chars
- [monday ticket] #1 "T" http://x (open)

### Open loops
- [open] check the dry run
"""
LESSON = "### What happened\nFirst pass.\n\n### Lessons\n- Only a lesson\n"
NEITHER = "### What happened\nA thin one.\n\n### Facts\n- Only a fact\n"
ID = "a177508f-1111-2222-3333-444455556666"
MARKED = f"{common.NEW_MARKER}\n**You:** go\n"

with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp).resolve()
    common.PENDING, common.LOG = tmp / "pending", tmp / "log"
    common.PENDING.mkdir()
    common.corpus = lambda: tmp / "notes"
    common.config = lambda: {**common.DEFAULTS, "log_dir": "sessions", "distil": False}
    days = tmp / "notes" / "sessions"
    seen = []

    def fresh(**entries):
        """An empty sessions folder holding day-file entries: {"2026-10-30": [(time, body), ...]}."""
        shutil.rmtree(days, ignore_errors=True)
        days.mkdir(parents=True)
        for day, found in entries.items():
            name = day.replace("_", "-")
            (days / f"{name}.md").write_text("".join(f"\n## Session {t} · a177508f\n\n{b}" for t, b in found))

    def run(name, reply, text="**You:** go\n"):
        staged = common.PENDING / name
        staged.write_text(text)
        distil.ask = lambda model, prompt, payload: (seen.append(payload), reply)[1]
        headless_run.main(staged)
        return staged

    def written():
        return "".join(p.read_text() for p in sorted(days.glob("*.md")))

    # a first entry: no Already recorded block, no backlink, no marker
    fresh()
    run(f"{ID}-20261030-103500.md", OLD, MARKED)
    assert seen[-1] == "**You:** go\n", "marker stripped from a first entry"
    assert "Continues" not in written() and "## Session 10:35 · a177508f\n" in written()

    # names that are no session id get a first entry, and no lookup
    fresh(**{"2026-10-30": [("10:35", OLD)]})
    headless_run.session_entries = lambda *a: (_ for _ in ()).throw(AssertionError("looked up"))
    for name in ("thin.md", "session-20261030-103500.md", "zzzzzzzz-1111-20261030-103500.md"):
        run(name, LESSON, MARKED)
        assert "Already recorded" not in seen[-1] and common.NEW_MARKER not in seen[-1], name
    headless_run.session_entries = real[5]

    # a continuation: backlink first, repeats dropped, a changed monday status kept
    fresh(**{"2026-10-30": [("10:35", OLD)]})
    reply = """### What happened
Resumed the digest work.

### Decisions
- Use Sonnet for digests.
- keep the OPENING!
- Drop the sweep

### Facts
- Budget is 40,000 chars
- [monday ticket] #1 "T" http://x (closed Done)

### Open loops
- [closed] check the dry run
"""
    staged = run(f"{ID}-20261102-091200.md", reply, MARKED)
    assert seen[-1] == f"Already recorded for this session:\n\n[2026-10-30 10:35, latest entry]\n{OLD.strip()}\n\n---\n\n{MARKED}"
    out = (days / "2026-11-02.md").read_text()
    assert "## Session 09:12 · a177508f\n" in out
    assert out.split("### What happened\n")[1].splitlines()[:2] == [
        "Continues [[sessions/2026-10-30#Session 10:35 · a177508f]].", "Resumed the digest work."]
    assert "Use Sonnet" not in out and "OPENING" not in out and "Budget is" not in out, "repeats dropped"
    assert "### Facts\n- [monday ticket]" in out and "(closed Done)" in out
    assert "Drop the sweep" in out and "[closed] check the dry run" in out and not staged.exists()
    assert (common.LOG / "digest.log").read_text().count("dropped a repeated") == 3

    # an identical monday bullet is a repeat; a model that omits the heading still gets the link
    run(f"{ID}-20261103-080000.md", '### Decisions\n- Fresh call\n\n### Facts\n- [monday ticket] #1 "T" http://x (open)\n')
    out = (days / "2026-11-03.md").read_text()
    assert "(open)" not in out and "Fresh call" in out
    assert out.split("\n## ")[1].split("\n", 2)[2].startswith(
        "### What happened\nContinues [[sessions/2026-11-02#Session 09:12 · a177508f]].\n\n### Decisions")

    # the payload: older entries' Decisions and Open loops, the latest in full, an older one with
    # neither section left out
    fresh(**{"2026-10-29": [("09:00", OLD), ("09:30", NEITHER)], "2026-10-30": [("10:35", LESSON)]})
    run(f"{ID}-20261103-090000.md", "### Facts\n- fresh\n", "**You:** more\n")
    assert seen[-1] == ("Already recorded for this session:\n\n"
                        "[2026-10-29 09:00, earlier entry]\n### Decisions\n- Use Sonnet for digests\n- Keep the opening\n"
                        "### Open loops\n- [open] check the dry run\n\n"
                        f"[2026-10-30 10:35, latest entry]\n{LESSON.strip()}\n\n---\n\n**You:** more\n"), seen[-1]

    # nothing left after dedupe: dropped, nothing appended
    before = written()
    staged = run(f"{ID}-20261104-080000.md", "### What happened\nAgain.\n\n### Decisions\n- Use Sonnet for digests\n"
                 "\n### Lessons\n- only a LESSON\n")
    assert written() == before and (common.PENDING / "dropped" / staged.name).exists()
    assert "nothing new was left" in (common.LOG / "digest.log").read_text()

distil.ask, common.corpus, common.config, common.PENDING, common.LOG, headless_run.session_entries = real
print("ok")
