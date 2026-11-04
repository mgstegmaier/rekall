#!/usr/bin/env python3
"""wins-mine.tags: the work tag matches a whole tag, never a substring ("framework" is not "work").
wins-mine.commits: reads every pushed branch of each [repos] mirror.
Run: python3 scripts/test_wins_mine.py (needs a rekall.toml or REKALL_CONFIG)"""
import contextlib
import importlib.util
import io
import subprocess
import sys
import tempfile
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

# A mirror holds commits on main and on a pushed feature branch; both count, other authors don't.
wm.AUTHOR = "Wins Author"  # --author is a regex: the suite's one-letter test names match anyone
tmp = Path(tempfile.mkdtemp())
work, mirror = tmp / "work", tmp / "repos" / "svc.git"
def git(*a, cwd=work):
    subprocess.run(["git", "-C", str(cwd), *a], check=True, capture_output=True)
subprocess.run(["git", "init", "-q", "-b", "main", str(work)], check=True)
def commit(msg, who):
    (work / f"{msg}.md").write_text(msg)
    git("add", ".")
    git("-c", f"user.name={who}", "-c", f"user.email={who}@example.com", "commit", "-q", "-m", msg)
commit("on-main", wm.AUTHOR)
git("checkout", "-q", "-b", "feature")
commit("on-feature", wm.AUTHOR)
commit("someone-else", "Other Person")
subprocess.run(["git", "init", "-q", "--bare", str(mirror)], check=True)
git("remote", "add", "origin", work.as_uri(), cwd=mirror)
git("config", "remote.origin.fetch", "+refs/heads/*:refs/remotes/origin/*", cwd=mirror)
git("fetch", "-q", "origin", cwd=mirror)
found = wm.commits("2000-01-01", [{"name": "svc", "mirror": mirror}])
subjects = {line.split(" ", 1)[1] for month in found.values() for line in month["svc"]}
assert subjects == {"on-main", "on-feature"}, subjects
assert wm.commits("2000-01-01", [{"name": "gone", "mirror": tmp / "nope.git"}]) == {}

# A leftover [wins].repos_dir gets one notice saying [repos] replaced it.
wm.WINS["repos_dir"] = "~/old"
wm.HISTORY = tmp / "no-history.jsonl"
wm.HISTORY.write_text("")
err = io.StringIO()
with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
    sys.argv = ["wins-mine.py", "--since", "2099-01-01"]
    wm.main()
assert "[repos] in rekall.toml replaced it" in err.getvalue(), err.getvalue()
print("ok")
