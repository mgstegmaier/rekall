#!/bin/bash
# Trigger for the Microsoft Graph ingest — launchd (weekdays, hourly at :45, 07:45-17:45) or manual.
# Off unless rekall.toml has [graph] enabled = true. Secrets: .env at the repo root first, then
# Doppler if installed. Plan: docs/plans/2026-10-16-rekall-graph-ingest.md.
export PATH="/opt/homebrew/bin:/usr/local/bin:/Library/Frameworks/Python.framework/Versions/3.13/bin:$HOME/.local/bin:$PATH"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${PYTHON:-$(command -v python3 || command -v python)}"
ENV_FILE="$SCRIPT_DIR/../.env"
if [ -f "$ENV_FILE" ]; then
  set -a; . "$ENV_FILE"; set +a
fi
# Ask Doppler only for what .env left blank, so a token the setup page wrote to .env wins.
NEED=""
for k in MSGRAPH_CLIENT_ID MSGRAPH_CLIENT_SECRET MSGRAPH_TENANT_ID MSGRAPH_REFRESH_TOKEN; do
  [ -z "${!k}" ] && NEED="$NEED,$k"
done
if [ -z "$NEED" ] || ! command -v doppler >/dev/null; then
  exec "$PYTHON" "$SCRIPT_DIR/graph-ingest.py" "$@"   # still missing: the script logs one line and exits 0
fi
exec doppler run --project heckatron --config dev --only-secrets "${NEED#,}" \
  -- "$PYTHON" "$SCRIPT_DIR/graph-ingest.py" "$@"
