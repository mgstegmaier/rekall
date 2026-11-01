"""session_end.filtered: a session that fits max_chars goes through whole; a longer one keeps its
opening and its end, cut at whole turns, with a marker saying how many turns were left out.
Run: python graph-memory/test_digest_filter.py"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "digest"))
import session_end  # noqa: E402

cfg = {**session_end.common.DEFAULTS, "max_chars": 2000}

with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp) / "s.jsonl"

    def write(bodies):
        roles = ("user", "assistant")
        path.write_text("\n".join(json.dumps({"type": roles[i % 2], "message": {
            "role": roles[i % 2], "content": body}}) for i, body in enumerate(bodies)))

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

print("ok")
