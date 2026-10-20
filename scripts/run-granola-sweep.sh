#!/bin/bash
# Trigger for the Granola sweep — launchd (weekdays, hourly at :30, 07:30-17:30) or manual.
# Off unless GRANOLA_API_KEY is found (the script logs one line and exits 0 without it).
# Plan: vault wiki/plans/2026-09-15-granola-sweep.md.
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
exec $PREFIX "$PYTHON" "$SCRIPT_DIR/granola-sweep.py" "$@"
