#!/bin/bash
# Trigger for the Fathom pipeline — used by launchd (hourly, 7am-7pm) and manually (/fathom-sync).
# Secrets come from .env at the repo root when it exists, otherwise from Doppler.
# Plan: docs/plans/2026-08-21-wiki-revival-fathom-pipeline.md (Phase 4).
export PATH="/opt/homebrew/bin:/usr/local/bin:/Library/Frameworks/Python.framework/Versions/3.13/bin:$HOME/.local/bin:$PATH"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/../.env"
if [ -f "$ENV_FILE" ]; then
  set -a; . "$ENV_FILE"; set +a
  exec python3 "$SCRIPT_DIR/fathom-pipeline.py" "$@"
fi
exec doppler run --project heckatron --config dev -- python3 "$SCRIPT_DIR/fathom-pipeline.py" "$@"
