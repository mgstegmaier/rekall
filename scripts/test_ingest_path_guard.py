#!/usr/bin/env python3
"""Checks the PreToolUse guard denies what it must. Run it directly: python3 scripts/test_ingest_path_guard.py"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

GUARD = Path(__file__).parent / "ingest-path-guard.py"


def call(tool_input, roots, tool="Read"):
    """Returns the permissionDecision, or None when the guard stayed silent (allow)."""
    env = {**os.environ, "REKALL_GUARD_ROOTS": os.pathsep.join(str(r) for r in roots)}
    if roots is None:
        env.pop("REKALL_GUARD_ROOTS", None)
    out = subprocess.run(
        [sys.executable, str(GUARD)],
        input=json.dumps({"tool_name": tool, "tool_input": tool_input}),
        capture_output=True, text=True, env=env,
    )
    assert out.returncode == 0, f"guard must exit 0, got {out.returncode}: {out.stderr}"
    if not out.stdout.strip():
        return None
    return json.loads(out.stdout)["hookSpecificOutput"]["permissionDecision"]


def main():
    with tempfile.TemporaryDirectory() as tmp:
        vault = Path(tmp) / "vault"
        (vault / "wiki").mkdir(parents=True)
        inside = vault / "wiki" / "note.md"
        inside.write_text("x")
        roots = [vault]

        assert call({"file_path": str(inside)}, roots) is None, "a file in the vault must be allowed"
        assert call({"file_path": str(vault)}, roots) is None, "the root itself must be allowed"
        assert call({"file_path": str(Path.home() / ".ssh" / "id_rsa")}, roots) == "deny", "~/.ssh must be denied"
        assert call({"file_path": "/etc/passwd"}, roots) == "deny", "/etc must be denied"
        assert call({"file_path": str(vault) + "/../secret.env"}, roots) == "deny", "traversal out must be denied"

        # A symlink planted inside the vault must not become a way out of it.
        link = vault / "wiki" / "escape"
        link.symlink_to(Path(tmp) / "outside.txt")
        (Path(tmp) / "outside.txt").write_text("secret")
        assert call({"file_path": str(link)}, roots) == "deny", "symlink out of the vault must be denied"

        # Grep and Glob carry their path under `path`, and Write/Edit under `file_path`.
        assert call({"path": "/etc"}, roots, tool="Grep") == "deny", "Grep outside must be denied"
        assert call({"path": str(vault)}, roots, tool="Glob") is None, "Glob inside must be allowed"
        assert call({"file_path": "/tmp/evil.md"}, roots, tool="Write") == "deny", "Write outside must be denied"

        # A tool input with no path at all is not the guard's business.
        assert call({"pattern": "TODO"}, roots, tool="Grep") is None, "a pathless call must pass through"

        # Misconfiguration fails closed rather than open.
        assert call({"file_path": str(inside)}, []) == "deny", "an empty allowlist must deny"

        # A second root is honored, since ingest also reads the wiki skill.
        other = Path(tmp) / "skills"
        other.mkdir()
        assert call({"file_path": str(other / "SKILL.md")}, [vault, other]) is None, "a second root must be allowed"

    print("ingest path guard: all checks pass")


if __name__ == "__main__":
    main()
