#!/bin/bash
# Refresh the bare mirrors of the repos listed under [repos] in rekall.toml (repo_sync.py).
# Run by launchd/com.rekall.repo-sync.plist at 07:00 and 13:00; safe to run by hand any time.
HERE="$(cd "$(dirname "$0")" && pwd)"
PY="$HERE/.venv/bin/python"
[ -x "$PY" ] || PY="$HERE/.venv/Scripts/python.exe"   # Windows venv layout
# ponytail: launchd appends to this script's log forever; truncate in place (same inode) past ~1MB.
# Path matches __STATE__/logs/ in launchd/com.rekall.repo-sync.plist; an empty lookup skips it.
STATE="$("$PY" "$HERE/../rekall_config.py" STATE_DIR)"
LOG="$STATE/logs/repo-sync.log"
if [ -n "$STATE" ] && [ -f "$LOG" ] && [ "$(wc -c < "$LOG")" -gt 1000000 ]; then
    tail -n 2000 "$LOG" > "$LOG.tmp" && cat "$LOG.tmp" > "$LOG" && rm -f "$LOG.tmp"
fi
# [secrets] run_prefix in rekall.toml (e.g. "doppler run ... --") wraps the job; unset runs it bare.
# Word-split on purpose: the prefix is a command line.
PREFIX="$("$PY" "$HERE/../rekall_config.py" RUN_PREFIX)"
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$PATH"  # launchd's PATH lacks gh and a Homebrew run_prefix (doppler)
export PYTHONUTF8=1
echo "--- $(date '+%Y-%m-%d %H:%M:%S') repo-sync"
$PREFIX "$PY" "$HERE/repo_sync.py"
