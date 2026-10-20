#!/bin/bash
# Trigger for the Microsoft Graph ingest — launchd (weekdays, hourly at :45, 07:45-17:45) or manual.
# Off unless rekall.toml has [graph] enabled = true. Secrets: read by the script. Plan: docs/plans/2026-10-16-rekall-graph-ingest.md.
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
exec $PREFIX "$PYTHON" "$SCRIPT_DIR/graph-ingest.py" "$@"
