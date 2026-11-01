#!/bin/bash
# Nightly wiki lint — launchd and Task Scheduler (21:30) or manual. The lifecycle job that moves
# `status: archive` files to wiki/archive/ runs only on Sundays (`date +%u` = 7); it found nothing
# to do most weeknights.
# ponytail: launchd appends to its stdout log forever with no logrotate; truncate in place
# (same inode, so the open fd keeps writing) past ~1MB. Path matches launchd/com.rekall.wiki-lint.plist.
LOG="$HOME/.config/rekall/logs/wiki-lint-launchd.log"
if [ -f "$LOG" ] && [ "$(wc -c < "$LOG")" -gt 1000000 ]; then
    tail -n 2000 "$LOG" > "$LOG.tmp" && cat "$LOG.tmp" > "$LOG" && rm -f "$LOG.tmp"
fi
export PATH="/opt/homebrew/bin:/usr/local/bin:/Library/Frameworks/Python.framework/Versions/3.13/bin:$HOME/.local/bin:$PATH"
# Windows Python defaults to cp1252 for open/read_text/write_text; UTF-8 mode makes it match macOS.
export PYTHONUTF8=1
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$SCRIPT_DIR/../graph-memory/.venv"
[ -x "$VENV/bin/python" ] && : "${PYTHON:=$VENV/bin/python}"
[ -x "$VENV/Scripts/python.exe" ] && : "${PYTHON:=$VENV/Scripts/python.exe}"
PYTHON="${PYTHON:-$(command -v python3 || command -v python)}"
# [secrets] run_prefix in rekall.toml (e.g. "doppler run ... --") wraps the job; unset runs it bare.
# Word-split on purpose: the prefix is a command line.
PREFIX="$("$PYTHON" "$SCRIPT_DIR/../rekall_config.py" RUN_PREFIX)"
$PREFIX "$PYTHON" "$SCRIPT_DIR/wiki-lint.py"
[ "$(date +%u)" = 7 ] && $PREFIX "$PYTHON" "$SCRIPT_DIR/wiki-cleanup.py" --execute
true
