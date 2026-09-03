#!/bin/bash
# Rebuild the wiki RAG index + graph. Safe to run any time; both are disposable.
HERE="$(cd "$(dirname "$0")" && pwd)"
PY="$HERE/.venv/bin/python"
WIKI="$("$PY" "$HERE/../rekall_config.py" WIKI)"
SESSIONS="$("$PY" "$HERE/../rekall_config.py" SESSIONS)"
export PATH="$HOME/.local/bin:$PATH"  # launchd's PATH lacks claude
# distil any new/changed meeting notes and raw/ sources first (SHA256 state makes
# this incremental, usually zero claude calls); the index build below picks up its
# output. raw/ is distilled because a long source can answer questions the compiled
# wiki page never surfaced (decided 2026-09-03).
"$PY" "$HERE/distil.py" "$WIKI" --under meetings --no-rebuild
"$PY" "$HERE/distil.py" "$WIKI" --under raw --no-rebuild
# incremental by default; build_index.py promotes the first Sunday run each week
# to a full rebuild on its own (last_full in rag.db's meta table)
"$PY" "$HERE/build_index.py" --corpus "$WIKI" --extra "$SESSIONS"
"$PY" "$HERE/build_graph.py" --corpus "$WIKI" --extra "$SESSIONS"
