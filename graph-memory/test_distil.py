"""distil.run: a note that fails distillation twice in a row on the same hash
is quarantined (no third claude call) until it's edited; distil_model in
digest/config.json is its own key, defaulting to haiku, separate from the
session digest's "model" (sonnet)."""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import distil  # noqa: E402

with tempfile.TemporaryDirectory() as tmp:
    corpus = Path(tmp) / "notes"
    corpus.mkdir()
    note = corpus / "flaky.md"
    note.write_text("# Flaky\n\nThis note has no clean quote to extract, sadly.\n")

    distil.DISTILLED = Path(tmp) / "distilled"
    distil.STATE = distil.DISTILLED / ".state.json"

    calls = []

    def bad_ask(model, prompt_text, payload):
        calls.append(payload)
        return "no question or quote in here"  # parse_entry finds neither -> dropped

    distil.ask = bad_ask

    counts = distil.run(corpus, rebuild=False)
    assert counts == {"distilled": 0, "skipped": 0, "dropped": 1}, counts
    assert len(calls) == 1

    counts = distil.run(corpus, rebuild=False)  # 2nd consecutive failure -> quarantined
    assert counts == {"distilled": 0, "skipped": 0, "dropped": 1}, counts
    assert len(calls) == 2

    counts = distil.run(corpus, rebuild=False)  # quarantined: no 3rd call
    assert counts == {"distilled": 0, "skipped": 1, "dropped": 0}, counts
    assert len(calls) == 2

    note.write_text("# Flaky\n\nStill no quote, but the hash changed now.\n")
    counts = distil.run(corpus, rebuild=False)  # hash moved -> failure count resets, retried
    assert counts == {"distilled": 0, "skipped": 0, "dropped": 1}, counts
    assert len(calls) == 3

with tempfile.TemporaryDirectory() as tmp:
    cfg = Path(tmp) / "config.json"
    distil.CONFIG = cfg
    assert distil.model_name() == "haiku"  # no config file at all
    cfg.write_text(json.dumps({"model": "sonnet"}))
    assert distil.model_name() == "haiku"  # digest's model key doesn't leak in
    cfg.write_text(json.dumps({"model": "sonnet", "distil_model": "opus"}))
    assert distil.model_name() == "opus"  # its own key wins

print("ok")
