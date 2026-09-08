#!/bin/bash
# Trigger for the calendar watch — launchd every 15 minutes, or by hand.
# Secrets come from .env at the repo root when it has them, otherwise from Doppler.
# Same shape as scripts/run-fathom-pipeline.sh.
export PATH="/opt/homebrew/bin:/usr/local/bin:/Library/Frameworks/Python.framework/Versions/3.13/bin:$HOME/.local/bin:$PATH"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/../.env"
if [ -f "$ENV_FILE" ]; then
  set -a; . "$ENV_FILE"; set +a
fi
if [ -n "$MSGRAPH_REFRESH_TOKEN" ]; then
  exec python3 "$SCRIPT_DIR/calendar-watch.py" "$@"
fi
exec doppler run --project heckatron --config dev -- python3 "$SCRIPT_DIR/calendar-watch.py" "$@"
