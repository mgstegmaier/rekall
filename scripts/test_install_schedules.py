"""install.sh step 7: a job another LaunchAgent already runs (a hand-made plist under another label)
is skipped, not scheduled twice. Runs scheduled_elsewhere (pulled out of install.sh) against a temp dir."""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO = "/r/rekall"


def fn():
    src = (ROOT / "install.sh").read_text(encoding="utf-8")
    return re.search(r"^scheduled_elsewhere\(\) \{.*?^\}\n", src, re.S | re.M).group(0)


def check(agents, label):
    r = subprocess.run(["bash", "-c", fn() + f'scheduled_elsewhere "{label}"'],
                       env={"AGENTS": str(agents), "REPO": REPO, "PATH": "/usr/bin:/bin"},
                       capture_output=True, text=True)
    return r.returncode, r.stdout.strip()


def test_skips_a_job_another_label_runs(tmp_path):
    lint = "com.rekall.wiki-lint"
    (tmp_path / f"{lint}.plist.new").write_text(f"<string>{REPO}/scripts/run-wiki-lint.sh</string>")
    (tmp_path / f"{lint}.plist").write_text(f"<string>{REPO}/scripts/run-wiki-lint.sh</string>")  # our own copy
    (tmp_path / "com.other.thing.plist").write_text("<string>/elsewhere/job.sh</string>")
    assert check(tmp_path, lint) == (1, ""), "our own plist and unrelated agents don't count"

    legacy = tmp_path / "com.someone.wiki-lint.plist"
    legacy.write_text(f"<string>/bin/bash</string><string>{REPO}/scripts/run-wiki-lint.sh</string>")
    assert check(tmp_path, lint) == (0, str(legacy))
