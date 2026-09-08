#!/bin/bash
# Friday status runner: launchd (Friday 15:00) and manual. Runs the /status skill headless so
# today.md carries the week's facts and a draft message before the end of the day.
# Pattern copied from familiar's run-one-percent.sh, minus the failure stub: there is no page to
# replace, the block simply keeps last week's facts or is absent.
export PATH="/opt/homebrew/bin:/usr/local/bin:/Library/Frameworks/Python.framework/Versions/3.13/bin:$HOME/.local/bin:$PATH"
unset ANTHROPIC_API_KEY   # bill the subscription login, not API
export REKALL_NO_DIGEST=1  # a chief-of-staff run leaves no session digest (see session_end.py)
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# launchd starts us in /; run from the repo so the session has a project and the skills.
cd "$REPO" || exit 1
LOG="$HOME/.config/rekall/logs/status.log"
mkdir -p "$(dirname "$LOG")"
if [ -f "$REPO/.env" ]; then
  set -a; . "$REPO/.env"; set +a
fi
# ponytail: install.sh stubs .env from .env.example, so gate on the secret, not the file.
if [ -n "$MONDAY_API_TOKEN" ]; then
  WRAP=()
else
  WRAP=(doppler run --project heckatron --config dev --)
fi

log() { printf '[%s] %.300s\n' "$(date '+%F %T')" "$*" >> "$LOG"; }

run_once() {
  # Stream claude's events into the log, timestamped and truncated, so after a watchdog kill
  # the last line names what the session was doing. bypassPermissions because headless has no
  # approver; stdin from /dev/null so nothing can wait on input.
  "${WRAP[@]}" claude -p "/status" --permission-mode bypassPermissions \
    --allowedTools "Read,Bash,Edit,Write" \
    --output-format stream-json --verbose </dev/null \
    > >(while IFS= read -r line; do log "$line"; done) 2>&1 &
  CPID=$!
  ( sleep 1800; kill -9 "$CPID" 2>/dev/null && log "WATCHDOG: killed hung run after 30m" ) &
  WPID=$!
  disown "$WPID"
  wait "$CPID"; rc=$?
  kill "$WPID" 2>/dev/null
  return $rc
}

log "status run starting"
run_once; rc=$?
if [ $rc -ne 0 ]; then
  log "attempt 1 failed (exit $rc), retrying"
  run_once; rc=$?
fi
log "status run finished (exit $rc)"
exit $rc
