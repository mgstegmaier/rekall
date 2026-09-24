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
export PATH="$HOME/.local/bin:$PATH"  # launchd's PATH lacks claude
# distil any new/changed meeting notes and raw/ sources first (SHA256 state makes
# this incremental, usually zero claude calls); the index build below picks up its
# output. raw/ is distilled because a long source can answer questions the compiled
# wiki page never surfaced (decided 2026-09-03).
"$PY" "$HERE/distil.py" "$WIKI" --under meetings --no-rebuild
"$PY" "$HERE/distil.py" "$WIKI" --under raw --no-rebuild
# incremental by default; build_index.py promotes the first Sunday run each week
# to a full rebuild on its own (last_full in rag.db's meta table)
"$PY" "$HERE/build_index.py" --corpus "$WIKI"
"$PY" "$HERE/build_graph.py" --corpus "$WIKI"
