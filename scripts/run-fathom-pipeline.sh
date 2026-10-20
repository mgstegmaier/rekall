#!/bin/bash
# Trigger for the Fathom pipeline — used by launchd (hourly, 7am-7pm) and manually (/fathom-sync).
# Secrets: environment, OS keyring, or .env, read by the script (rekall_config.get_secret).
# Plan: docs/plans/2026-08-21-wiki-revival-fathom-pipeline.md (Phase 4).
# ponytail: same no-logrotate problem as graph-memory/reindex.sh, hourly job, 13x/weekday.
# Truncate in place (same inode) so launchd's open log fd keeps writing correctly.
LOG="$HOME/.config/rekall/logs/launchd.log"
if [ -f "$LOG" ] && [ "$(wc -c < "$LOG")" -gt 1000000 ]; then
    tail -n 2000 "$LOG" > "$LOG.tmp" && cat "$LOG.tmp" > "$LOG" && rm -f "$LOG.tmp"
fi
export PATH="/opt/homebrew/bin:/usr/local/bin:/Library/Frameworks/Python.framework/Versions/3.13/bin:$HOME/.local/bin:$PATH"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# The venv has keyring; system python would skip the Keychain without a word.
VENV="$SCRIPT_DIR/../graph-memory/.venv"
[ -x "$VENV/bin/python" ] && : "${PYTHON:=$VENV/bin/python}"
[ -x "$VENV/Scripts/python.exe" ] && : "${PYTHON:=$VENV/Scripts/python.exe}"
PYTHON="${PYTHON:-$(command -v python3 || command -v python)}"
# [secrets] run_prefix in rekall.toml (e.g. "doppler run ... --") wraps the job; unset runs it bare.
# Word-split on purpose: the prefix is a command line.
PREFIX="$("$PYTHON" "$SCRIPT_DIR/../rekall_config.py" RUN_PREFIX)"
exec $PREFIX "$PYTHON" "$SCRIPT_DIR/fathom-pipeline.py" "$@"
