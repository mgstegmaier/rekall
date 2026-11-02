"""R-docs-12: the README layout block names the schedule templates, skills and commands the
repo actually holds."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def listed(folder):
    m = re.search(rf"^├── {folder}/\s+# [^:]*: (.+)$", (ROOT / "README.md").read_text(encoding="utf-8"), re.M)
    assert m, f"README layout has no {folder}/ line"
    return {n.strip() for n in m.group(1).split(",")}


def held(folder, pattern):
    names = (re.fullmatch(pattern, p.name) for p in (ROOT / folder).iterdir())
    return {m.group(1) for m in names if m}


def test_launchd():
    assert listed("launchd") == held("launchd", r"com\.rekall\.(.+)\.plist")


def test_windows():
    assert listed("windows") == held("windows", r"com\.rekall\.(.+)\.xml")


def test_skills_and_commands():
    assert listed("skills") == {p.name for p in (ROOT / "skills").iterdir() if p.is_dir()}
    assert listed("commands") == held("commands", r"(.+)\.md")
