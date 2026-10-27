#!/usr/bin/env python3
"""wins-mine.tags: the work tag matches a whole tag, never a substring ("framework" is not "work").
Run: python3 scripts/test_wins_mine.py (needs a rekall.toml or REKALL_CONFIG)"""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("wins_mine", Path(__file__).parent / "wins-mine.py")
wm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wm)

assert wm.tags("type: project\ntags: [Work, data]\n") == {"work", "data"}
assert wm.tags("tags: work\ntitle: x\n") == {"work"}
assert wm.tags("tags:\n  - work\n  - data-eng\ntitle: x\n") == {"work", "data-eng"}
assert "work" not in wm.tags("tags: [framework, homework]\n"), "a substring is not the tag"
assert "work" not in wm.tags("title: Work plan\ntags: [x]\n"), "only the tags list counts"
assert wm.tags("title: no tags\n") == set()
print("ok")
