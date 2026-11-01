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
# [secrets] run_prefix in rekall.toml (e.g. "doppler run ... --") wraps each job; unset runs it bare.
# Word-split on purpose: the prefix is a command line.
PREFIX="$("$PY" "$HERE/../rekall_config.py" RUN_PREFIX)"
export PATH="/opt/homebrew/bin:/usr/local/bin:/Library/Frameworks/Python.framework/Versions/3.13/bin:$HOME/.local/bin:$PATH"  # launchd's PATH lacks claude and a Homebrew run_prefix (doppler)
# Windows Python defaults to cp1252 for open/read_text/write_text; UTF-8 mode makes it match macOS.
export PYTHONUTF8=1
# session digests that failed to write up (expired sign-in, outage) wait in digest/pending/;
# retry the ones older than 10 minutes, stopping at the first sign-in failure
$PREFIX "$PY" "$HERE/digest/headless_run.py" --drain || true
# distil any new/changed meeting notes and raw/ sources first (SHA256 state makes
# this incremental, usually zero claude calls); the index build below picks up its
# output. raw/ is distilled because a long source can answer questions the compiled
# wiki page never surfaced (decided 2026-09-03).
$PREFIX "$PY" "$HERE/distil.py" "$WIKI" --under meetings --no-rebuild
$PREFIX "$PY" "$HERE/distil.py" "$WIKI" --under raw --no-rebuild
# incremental by default; build_index.py promotes the first Sunday run each week
# to a full rebuild on its own (last_full in rag.db's meta table)
$PREFIX "$PY" "$HERE/build_index.py" --corpus "$WIKI"
$PREFIX "$PY" "$HERE/build_graph.py" --corpus "$WIKI"
