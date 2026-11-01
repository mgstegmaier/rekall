"""install.sh's settings merge: one recall hook per install, other tools' hooks untouched.
Runs the merge's Python (pulled out of install.sh) against a temp settings.json, never the real HOME."""
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def merge_py():
    src = (ROOT / "install.sh").read_text(encoding="utf-8")
    return re.search(r"settings\(\) \{.*?<<'EOF'\n(.*?)\nEOF\n", src, re.S).group(1)


def run(mode, path):
    subprocess.run([sys.executable, "-c", merge_py(), mode, str(ROOT), str(path), "/v/bin/python", "Bash(x:*)"],
                   check=True)
    return json.loads(path.read_text())


def cmds(s, event):
    return [h["command"] for g in s["hooks"].get(event, []) for h in g.get("hooks", [])]


def count(s, needle):
    return sum(needle in c for ev in s["hooks"] for c in cmds(s, ev))


def test_one_recall_hook_per_install(tmp_path):
    p = tmp_path / "settings.json"
    other = {"type": "command", "command": "astro-cli-hook.sh"}
    p.write_text(json.dumps({"hooks": {
        # recall is the SECOND hook of its group, as on the live settings
        "UserPromptSubmit": [{"hooks": [other, {"type": "command",
                                                "command": f'"{ROOT}/graph-memory/recall_hook.py"'}]},
                             {"matcher": "x"}, {"hooks": []}],  # foreign groups with no/empty hooks
        "SessionEnd": [{"hooks": [{"type": "command", "command": "undernet-end.sh"}]}],
    }}))
    for mode, want in [("add", 1), ("add", 1), ("remove", 0), ("add", 1)]:
        s = run(mode, p)
        assert count(s, "recall_hook.py") == want, mode
        assert "astro-cli-hook.sh" in cmds(s, "UserPromptSubmit"), mode
        assert {"matcher": "x"} in s["hooks"]["UserPromptSubmit"], mode
        assert {"hooks": []} in s["hooks"]["UserPromptSubmit"], mode
        assert "undernet-end.sh" in cmds(s, "SessionEnd"), mode
