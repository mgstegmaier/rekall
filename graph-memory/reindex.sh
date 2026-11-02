#!/bin/bash
# Rebuild the wiki RAG index + graph. Safe to run any time; both are disposable.
# ponytail: launchd appends to this script's own stdout/stderr log forever with no
# logrotate on the box; truncate in place (same inode, so launchd's open fd keeps
# writing to the right file) once it passes ~1MB. Path matches launchd/com.rekall.wiki-reindex.plist.
LOG="$HOME/.config/rekall/logs/wiki-reindex.log"
if [ -f "$LOG" ] && [ "$(wc -c < "$LOG")" -gt 1000000 ]; then
    tail -n 2000 "$LOG" > "$LOG.tmp" && cat "$LOG.tmp" > "$LOG" && rm -f "$LOG.tmp"
fi
HERE="$(cd "$(dirname "$0")" && pwd)"
PY="$HERE/.venv/bin/python"
[ -x "$PY" ] || PY="$HERE/.venv/Scripts/python.exe"   # Windows venv layout
WIKI="$("$PY" "$HERE/../rekall_config.py" WIKI)"
# an empty WIKI would make --corpus "" index launchd's working directory (/), and a missing
# folder would commit an empty index; stop before any step runs
[ -n "$WIKI" ] && [ -d "$WIKI" ] || { echo "FAILED config: WIKI is empty or missing ($WIKI)"; exit 2; }
# [secrets] run_prefix in rekall.toml (e.g. "doppler run ... --") wraps each job; unset runs it bare.
# Word-split on purpose: the prefix is a command line.
PREFIX="$("$PY" "$HERE/../rekall_config.py" RUN_PREFIX)"
export PATH="/opt/homebrew/bin:/usr/local/bin:/Library/Frameworks/Python.framework/Versions/3.13/bin:$HOME/.local/bin:$PATH"  # launchd's PATH lacks claude and a Homebrew run_prefix (doppler)
# Windows Python defaults to cp1252 for open/read_text/write_text; UTF-8 mode makes it match macOS.
export PYTHONUTF8=1
# session digests that failed to write up (expired sign-in, outage) wait in digest/pending/;
# retry the ones older than 10 minutes, stopping at the first sign-in failure
$PREFIX "$PY" "$HERE/digest/headless_run.py" --drain || true
# distil failures go to the digest log, and a signed-out distil exits 0, so neither
# distil step counts toward this script's exit status.
# distil any new/changed meeting notes and raw/ sources first (SHA256 state makes
# this incremental, usually zero claude calls); the index build below picks up its
# output. raw/ is distilled because a long source can answer questions the compiled
# wiki page never surfaced (decided 2026-09-03).
$PREFIX "$PY" "$HERE/distil.py" "$WIKI" --under meetings --no-rebuild
$PREFIX "$PY" "$HERE/distil.py" "$WIKI" --under raw --no-rebuild
# incremental by default; build_index.py promotes a run to a full rebuild on its own:
# the first Sunday run each week, every run once the last full is more than 7 days old,
# and the next run after an embedding-model change (re-embeds everything).
# A failed builder changes nothing in rag.db; it logs one FAILED line and the script
# exits non-zero (launchd's "last exit code"), while the other builder still runs.
rc=0
$PREFIX "$PY" "$HERE/build_index.py" --corpus "$WIKI" || { echo "FAILED build_index rc=$?"; rc=1; }
$PREFIX "$PY" "$HERE/build_graph.py" --corpus "$WIKI" || { echo "FAILED build_graph rc=$?"; rc=1; }
exit $rc
