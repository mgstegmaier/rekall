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
import rekall_config  # noqa: E402  (distil put the repo root on sys.path)

REAL_ASK = distil.ask

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

# The shipped config sits beside the digest scripts, and model_name() must read that file.
assert distil.CONFIG.is_file(), f"distil reads a config that isn't there: {distil.CONFIG}"

with tempfile.TemporaryDirectory() as tmp:
    corpus = Path(tmp) / "notes"
    corpus.mkdir()
    (corpus / "boom.md").write_text("# Boom\n\nclaude errors on this one every time.\n")
    distil.DISTILLED = Path(tmp) / "distilled"
    distil.STATE = distil.DISTILLED / ".state.json"
    calls = []

    def signed_out(model, prompt_text, payload):
        calls.append(payload)
        raise distil.NotSignedIn("not signed in")

    distil.ask = signed_out
    for _ in range(3):  # a sign-in failure stops the run and never quarantines
        assert distil.run(corpus, rebuild=False) == {"distilled": 0, "skipped": 0, "dropped": 0}
    assert len(calls) == 3

    def errors(model, prompt_text, payload):
        calls.append(payload)
        raise RuntimeError("claude exited 1")

    distil.ask = errors
    distil.run(corpus, rebuild=False)
    distil.run(corpus, rebuild=False)  # second error in a row on the same hash -> quarantined
    assert distil.run(corpus, rebuild=False) == {"distilled": 0, "skipped": 1, "dropped": 0}
    assert len(calls) == 5, "an erroring note must stop costing a call per run"

with tempfile.TemporaryDirectory() as tmp:
    cfg = Path(tmp) / "config.json"
    distil.CONFIG = cfg
    assert distil.model_name() == "haiku"  # no config file at all
    cfg.write_text(json.dumps({"model": "sonnet"}))
    assert distil.model_name() == "haiku"  # digest's model key doesn't leak in
    cfg.write_text(json.dumps({"model": "sonnet", "distil_model": "opus"}))
    assert distil.model_name() == "opus"  # its own key wins

# The shared runner, through the real ask() and a stand-in claude on PATH: an expired sign-in
# printed to stdout raises NotSignedIn and sets the marker; an error is quoted from stdout;
# a good answer that happens to say "401" is not mistaken for an auth failure.
with tempfile.TemporaryDirectory() as tmp:
    import os
    fake = Path(tmp) / "claude"
    os.environ["PATH"] = f"{tmp}{os.pathsep}{os.environ['PATH']}"
    os.environ["ANTHROPIC_API_KEY"] = "sk-should-not-reach-the-child"
    rekall_config.prompt_reauth = lambda: None  # no dialog from a test
    rekall_config.AUTH_FAILED = Path(tmp) / "claude-auth-failed"

    def script(body):
        fake.write_text("#!/bin/sh\n" + body)
        fake.chmod(0o755)

    script('echo "Failed to authenticate: OAuth session expired and could not be refreshed"; exit 1\n')
    try:
        REAL_ASK("haiku", "p", "x")
        raise AssertionError("an expired sign-in must raise NotSignedIn")
    except distil.NotSignedIn:
        pass
    assert rekall_config.AUTH_FAILED.exists(), "an auth failure must write the claude-auth-failed marker"

    script('echo "overloaded, try later"; exit 1\n')
    try:
        REAL_ASK("haiku", "p", "x")
        raise AssertionError("a failed call must raise")
    except distil.NotSignedIn:
        raise AssertionError("a non-auth failure is not a sign-in failure")
    except RuntimeError as exc:
        assert "overloaded" in str(exc), f"the error text on stdout must reach the message: {exc}"

    script('[ -z "$ANTHROPIC_API_KEY" ] && [ "$MEMORY_STARTER_CHILD" = 1 ] && echo "- What does a 401 mean?"\n')
    assert "401" in REAL_ASK("haiku", "p", "x"), "the child must run without the API key and with our marker"
    assert not rekall_config.AUTH_FAILED.exists(), "a success clears the marker"

print("ok")
