"""session_end.filtered: a session that fits max_chars goes through whole; a longer one keeps its
opening and its end, cut at whole turns, with a marker saying how many turns were left out.
Run: python graph-memory/test_digest_filter.py"""
import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "digest"))
import session_end  # noqa: E402

cfg = {**session_end.common.DEFAULTS, "max_chars": 2000}

with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp) / "s.jsonl"

    base = datetime(2026, 1, 1, 12, 0)  # naive local time; the transcript carries it as UTC

    def write(bodies):
        roles = ("user", "assistant")
        path.write_text("\n".join(json.dumps({
            "type": roles[i % 2],
            "timestamp": (base + timedelta(minutes=i)).astimezone().astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "message": {"role": roles[i % 2], "content": body}}) for i, body in enumerate(bodies)))

    write([f"turn {i}" for i in range(4)])
    assert session_end.filtered(path, cfg) is None, "under min_turns"

    write([f"turn {i}" for i in range(40)])
    text = session_end.filtered(path, cfg)
    assert "omitted" not in text and "turn 0" in text and "turn 39" in text, "fits, so whole"

    write([f"goal {'x' * 90}"] + [f"turn {i} {'y' * 90}" for i in range(1, 200)])
    text = session_end.filtered(path, cfg)
    assert len(text) <= cfg["max_chars"], len(text)
    assert text.startswith("**You:** goal"), "the opening survives"
    assert text.endswith("turn 199 " + "y" * 90), "the end survives"
    assert "turns omitted ...]" in text

    write(["z" * 5000] + [f"turn {i}" for i in range(1, 10)] + ["w" * 5000])
    text = session_end.filtered(path, cfg)
    assert len(text) <= cfg["max_chars"] + 20 and text.startswith("**You:** zzz"), "huge turns clipped"
    assert "www" in text, "the last turn survives even when it alone is too long"

    marker, since = session_end.common.NEW_MARKER, base + timedelta(minutes=19, seconds=30)
    write([f"turn {i}" for i in range(40)])
    text = session_end.filtered(path, cfg, since)
    assert text.count(marker) == 1 and f"{marker}\n**You:** turn 20" in text, "before the first newer turn"
    assert marker not in session_end.filtered(path, cfg), "no since, no marker"
    assert marker not in session_end.filtered(path, cfg, base + timedelta(hours=1)), "nothing newer"

    write([f"goal {'x' * 90}"] + [f"turn {i} {'y' * 90}" for i in range(1, 200)])
    text = session_end.filtered(path, cfg, base + timedelta(minutes=5, seconds=30))
    assert text.index("turns omitted ...]") < text.index(marker), "the middle is gone; the marker opens the tail"
    assert f"{marker}\n" in text and text.count(marker) == 1

    # one budget for the whole input: the marker counts, and a budget under the marker keeps no turns
    marker, since = session_end.common.NEW_MARKER, base + timedelta(minutes=2, seconds=30)
    write([f"turn {i}" for i in range(10)])
    whole = len("\n\n".join(f"**{'You' if i % 2 == 0 else 'Claude'}:** turn {i}" for i in range(10)))
    exact = {**cfg, "max_chars": whole + len(marker) + 1}
    text = session_end.filtered(path, exact, since)
    assert "omitted" not in text and len(text) == exact["max_chars"], (len(text), exact["max_chars"])
    text = session_end.filtered(path, {**cfg, "max_chars": exact["max_chars"] - 1}, since)
    assert "omitted" in text and len(text) <= exact["max_chars"] - 1, "one char short goes through the cut"
    tiny = session_end.filtered(path, {**cfg, "max_chars": 30}, since)
    assert tiny is None or len(tiny) <= 30, "a budget under the markers keeps no turns"

    # six closes of one session: the monday line, the recorded block and the transcript stay under max_chars
    headless_run = __import__("headless_run")
    common = session_end.common
    entry = "### What happened\n" + "Wired it. " * 30 + "\n\n### Decisions\n" + "".join(
        f"- decision {i} {'d' * 60}\n" for i in range(6)) + "\n### Open loops\n- [open] " + "o" * 80 + "\n"
    write([f"goal {'x' * 90}"] + [f"turn {i} {'y' * 90}" for i in range(1, 200)])
    monday = "[monday ticket] #1 \"T\" http://x (open)\n\n"
    earlier = []
    for close in range(6):
        prefix = common.recorded(earlier, cfg["max_chars"] // common.RECORDED_SHARE)
        room = cfg["max_chars"] - len(monday) - len(prefix)
        text = monday + session_end.filtered(path, cfg, base + timedelta(minutes=100), budget=room)
        sent = headless_run.payload(earlier, text, cfg["max_chars"]) if earlier else text
        assert len(sent) <= cfg["max_chars"], (close, len(sent))
        earlier.append(("2026-01-01", f"Session 12:0{close} \u00b7 a177508f", entry))

print("ok")
