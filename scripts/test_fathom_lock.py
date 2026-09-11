#!/usr/bin/env python3
"""Self-check: the pipeline's run lock keeps a second run out, on macOS and Windows.

acquire_lock has two implementations (fcntl.flock, msvcrt.locking) and one contract:
a second process gets None while the first holds it, and gets the lock once the first
exits. Both halves matter, because the hourly schedule and a manual /fathom-sync can
overlap.
Run: python3 scripts/test_fathom_lock.py
"""
import importlib.util
import subprocess
import sys
import tempfile
from pathlib import Path

PIPELINE = Path(__file__).resolve().parent / "fathom-pipeline.py"

CHILD = (
    "import importlib.util as u;"
    "s=u.spec_from_file_location('fp', r'{pipeline}');"
    "m=u.module_from_spec(s);s.loader.exec_module(m);"
    "print('got' if m.acquire_lock(r'{lock}') else 'none')"
)


def load():
    spec = importlib.util.spec_from_file_location("fathom_pipeline", PIPELINE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def child(lock):
    """What a second pipeline process sees. Its lock dies with it, by design."""
    out = subprocess.run([sys.executable, "-c", CHILD.format(pipeline=PIPELINE, lock=lock)],
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    return out.stdout.strip()


mod = load()
with tempfile.TemporaryDirectory() as tmp:
    lock = str(Path(tmp) / "fathom-pipeline.lock")

    held = mod.acquire_lock(lock)
    assert held is not None, "first acquire failed"
    assert child(lock) == "none", "a second process took the lock while it was held"

    held.close()  # what process exit does
    assert child(lock) == "got", "the lock was not released"

print("ok")
