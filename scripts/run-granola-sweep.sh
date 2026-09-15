#!/bin/bash
# Trigger for the Granola sweep — launchd (weekdays, hourly at :30, 07:30-17:30) or manual.
# Off unless GRANOLA_API_KEY is set: .env at the repo root first, then Doppler if installed.
# Plan: vault wiki/plans/2026-09-15-granola-sweep.md.
export PATH="/opt/homebrew/bin:/usr/local/bin:/Library/Frameworks/Python.framework/Versions/3.13/bin:$HOME/.local/bin:$PATH"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${PYTHON:-$(command -v python3 || command -v python)}"
ENV_FILE="$SCRIPT_DIR/../.env"
if [ -f "$ENV_FILE" ]; then
  set -a; . "$ENV_FILE"; set +a
fi
if [ -n "$GRANOLA_API_KEY" ] || ! command -v doppler >/dev/null; then
  exec "$PYTHON" "$SCRIPT_DIR/granola-sweep.py" "$@"   # no key: the script logs one line and exits 0
fi
exec doppler run --project heckatron --config dev \
  --only-secrets GRANOLA_API_KEY,JIRA_EMAIL \
  -- "$PYTHON" "$SCRIPT_DIR/granola-sweep.py" "$@"
