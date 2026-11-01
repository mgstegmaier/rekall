"""session_end.main: a session that closes again with nothing typed since its last close stages
nothing; one with a new prompt since then, or closing for the first time, is staged as before.
Run: python graph-memory/test_digest_skip.py"""
import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "digest"))
import session_end  # noqa: E402

common = session_end.common
real = session_end.read_stdin, session_end.spawn, common.corpus, common.config, common.LOG, common.PENDING

with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    common.LOG, common.PENDING = tmp / "log", tmp / "pending"
    common.LOG.mkdir()
    common.corpus = lambda: tmp
    common.config = lambda: {**common.DEFAULTS, "mode": "headless"}
    session_end.spawn = lambda staged: None
    transcript = tmp / "s.jsonl"
    session_end.read_stdin = lambda: {"transcript_path": str(transcript), "session_id": "abc"}
    start = datetime.now(timezone.utc) - timedelta(hours=3)

    def write(prompts):
        lines = []
        for i in range(prompts):
            when = (start + timedelta(minutes=10 * i)).isoformat().replace("+00:00", "Z")
            for role in ("user", "assistant"):
                lines.append(json.dumps({"type": role, "timestamp": when,
                                         "message": {"role": role, "content": f"{role} {i}"}}))
        transcript.write_text("\n".join(lines))

    def close_at(minutes):
        """Pretend an earlier write-up ran at start + minutes, local time, as its .out log shows."""
        stamp = (start + timedelta(minutes=minutes)).astimezone()
        (common.LOG / f"abc-{stamp:%Y%m%d-%H%M%S}.out").write_text("wrote ...")

    def staged():
        return sorted(common.PENDING.glob("*.md"))

    write(4)
    session_end.main()
    assert len(staged()) == 1, "a first close is staged"
    for p in staged():
        p.unlink()

    close_at(35)  # after the last prompt (minute 30)
    session_end.main()
    assert staged() == [], "closed again with nothing typed since: nothing staged"

    write(5)  # a prompt at minute 40, after that close
    session_end.main()
    assert len(staged()) == 1, "a new prompt since the last close is staged"

session_end.read_stdin, session_end.spawn, common.corpus, common.config, common.LOG, common.PENDING = real
print("ok")
