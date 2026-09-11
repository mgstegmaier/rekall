#!/bin/bash
# Trigger for the Fathom pipeline — used by launchd (hourly, 7am-7pm) and manually (/fathom-sync).
# Secrets come from .env at the repo root when it has them, otherwise from Doppler.
# Plan: docs/plans/2026-08-21-wiki-revival-fathom-pipeline.md (Phase 4).
export PATH="/opt/homebrew/bin:/usr/local/bin:/Library/Frameworks/Python.framework/Versions/3.13/bin:$HOME/.local/bin:$PATH"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${PYTHON:-$(command -v python3 || command -v python)}"
ENV_FILE="$SCRIPT_DIR/../.env"
if [ -f "$ENV_FILE" ]; then
  set -a; . "$ENV_FILE"; set +a
fi
# ponytail: install.sh stubs .env from .env.example, so file existence proves nothing.
# Gate on the secret itself or an all-empty stub silently shadows Doppler.
if [ -n "$FATHOM_API_KEY" ]; then
  exec "$PYTHON" "$SCRIPT_DIR/fathom-pipeline.py" "$@"
fi
# Only the three secrets the pipeline reads: a plain `doppler run` injects all 110 in heckatron/dev
# into this process, and the headless claude child plus every hook inherits them.
# JIRA_EMAIL, not WORK_EMAIL: WORK_EMAIL is a .env-only name, and fathom-pipeline.py
# falls back to JIRA_EMAIL, which is the one that exists in Doppler.
exec doppler run --project heckatron --config dev \
  --only-secrets FATHOM_API_KEY,MONDAY_API_TOKEN,JIRA_EMAIL \
  -- "$PYTHON" "$SCRIPT_DIR/fathom-pipeline.py" "$@"
