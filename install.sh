#!/bin/bash
# Rekall installer: every deterministic step of SETUP.md in one idempotent script.
# Run it after rekall.toml and .env exist. Safe to re-run; `--uninstall` reverses
# everything it did and leaves the repo, venv, .env and your wiki alone.
#
# Exists because the steps that write outside the repo (hooks into
# ~/.claude/settings.json, plists into ~/Library/LaunchAgents) get blocked when
# Claude Code performs them itself. Claude runs this script instead, and you
# approve one command: .claude/settings.json in this repo carries an ask rule so
# `bash install.sh` always prompts, in every permission mode.
#
# macOS and Windows. On Windows it runs under Git Bash, which Claude Code already
# requires, and the schedules become Task Scheduler tasks instead of launchd agents.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETTINGS="$HOME/.claude/settings.json"
AGENTS="$HOME/Library/LaunchAgents"
LOGS="$HOME/.config/rekall/logs"
VENV="$REPO/graph-memory/.venv"
DOMAIN="gui/$(id -u)"
LABELS="com.rekall.fathom-pipeline com.rekall.wiki-lint com.rekall.wiki-reindex"

case "$(uname -s)" in MINGW*|MSYS*|CYGWIN*) WIN=1 ;; *) WIN= ;; esac
if [ -n "$WIN" ]; then
  PY="$VENV/Scripts/python.exe"          # Windows venv layout
  LIST_RULE="Bash(schtasks /Query:*)"
else
  PY="$VENV/bin/python"
  LIST_RULE="Bash(launchctl list:*)"
fi
# GNU sed (Git Bash, Linux) takes no argument after -i; BSD sed (macOS) wants an empty
# suffix. Probe the binary rather than the OS: the wrong one silently mangles the file.
if sed --version >/dev/null 2>&1; then SEDI=(-i); else SEDI=(-i ''); fi

# 1. python 3.11+ (Apple's /usr/bin/python3 is too old, and python.org on Windows
# installs `python` rather than `python3`; prefer the newest one on PATH)
PY3=""
for c in python3.13 python3.12 python3.11 python3 python; do
  if command -v "$c" >/dev/null && "$c" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
    PY3="$(command -v "$c")"; break
  fi
done
[ -n "$PY3" ] || { echo "No python 3.11 or newer on PATH. Install one (brew install python, or python.org on Windows) and re-run." >&2; exit 1; }

# Merges (or removes) rekall's hooks and permission rules in settings.json.
# Matching is by exact command / rule string, so re-runs never duplicate.
settings() {  # $1 = add | remove
  mkdir -p "$(dirname "$SETTINGS")"
  [ -f "$SETTINGS" ] || echo '{}' > "$SETTINGS"
  "$PY3" - "$1" "$REPO" "$SETTINGS" "$PY" "$LIST_RULE" <<'EOF'
import json, sys
mode, repo, path, venv_py, list_rule = sys.argv[1:]
s = json.load(open(path))
ours = json.load(open(f"{repo}/hooks.json"))["hooks"]
hooks = s.setdefault("hooks", {})
for event, entries in ours.items():
    have = hooks.setdefault(event, [])
    for e in entries:
        e = json.loads(json.dumps(e).replace("__REPO__", repo).replace("__VENV_PY__", venv_py))
        cmd = e["hooks"][0]["command"]
        have[:] = [h for h in have if h.get("hooks", [{}])[0].get("command") != cmd]
        if mode == "add":
            have.append(e)
    if not have:
        del hooks[event]
if not hooks:
    del s["hooks"]
# install.sh itself is NOT allowed here on purpose: .claude/settings.json in the repo
# holds an ask rule so it always prompts (it writes outside the repo).
rules = [list_rule, f"Read({path})"]
allow = s.setdefault("permissions", {}).setdefault("allow", [])
allow[:] = [r for r in allow if r not in rules]
if mode == "add":
    allow.extend(rules)
if not allow:
    del s["permissions"]["allow"]
if not s["permissions"]:
    del s["permissions"]
json.dump(s, open(path, "w"), indent=2)
open(path, "a").write("\n")
EOF
}

# Copies a skill dir or command file to a temp path with __REPO__ filled in; prints the path.
render() {
  local out; out="$(mktemp -d)/$(basename "$1")"
  cp -R "$1" "$out"
  find "$out" -type f -exec sed "${SEDI[@]}" "s|__REPO__|$REPO|g" {} +
  ! grep -rq "__REPO__" "$out" || { echo "sed left __REPO__ unsubstituted in $out" >&2; exit 1; }
  echo "$out"
}

uninstall() {
  if [ -n "$WIN" ]; then
    for l in $LABELS; do
      powershell.exe -NoProfile -Command \
        "Unregister-ScheduledTask -TaskName '$l' -Confirm:\$false -ErrorAction SilentlyContinue" \
        >/dev/null 2>&1 || true
    done
  else
    for l in $LABELS; do
      launchctl bootout "$DOMAIN/$l" 2>/dev/null || true
      rm -f "$AGENTS/$l.plist"
    done
  fi
  settings remove
  # only remove skills/commands that still match what this repo installs; an edited copy stays
  for src in "$REPO"/skills/* "$REPO"/commands/*; do
    dst="$HOME/.claude/${src#"$REPO"/}"
    [ -e "$dst" ] && diff -rq "$(render "$src")" "$dst" >/dev/null && rm -r "$dst"
  done
  echo "Rekall uninstalled: schedules, hooks, skills and commands removed."
  echo "Kept: $REPO (with .venv and .env) and your wiki."
  exit 0
}
[ "${1:-}" = "--uninstall" ] && uninstall

[ -f "$REPO/rekall.toml" ] || { echo "rekall.toml is missing; write it first (SETUP.md step 3)." >&2; exit 1; }

# 2. secrets skeleton (values are yours to fill in; never overwritten)
[ -f "$REPO/.env" ] || cp "$REPO/.env.example" "$REPO/.env"
chmod 600 "$REPO/.env" 2>/dev/null || true   # no-op on Windows, where the profile is already user-only

# 3. venv, fastembed, embedding model
[ -x "$PY" ] || "$PY3" -m venv "$VENV"
"$PY" -c 'import fastembed' 2>/dev/null || "$PY" -m pip install -q fastembed
# Windows ships no timezone database, so zoneinfo raises without tzdata in the venv
[ -z "$WIN" ] || "$PY" -c 'import tzdata' 2>/dev/null || "$PY" -m pip install -q tzdata
MODEL_DIR="$("$PY" "$REPO/rekall_config.py" DATA)/model"
[ -f "$MODEL_DIR/model_optimized.onnx" ] || PYTHON="$PY" bash "$REPO/graph-memory/fetch_model.sh"

# 4. hooks + permission rules
settings add

# 5. skills and commands (skip anything already there)
for src in "$REPO"/skills/* "$REPO"/commands/*; do
  dst="$HOME/.claude/${src#"$REPO"/}"
  [ -e "$dst" ] && continue
  mkdir -p "$(dirname "$dst")"
  cp -R "$(render "$src")" "$dst"
done

# 6. schedules
mkdir -p "$LOGS"
if [ -n "$WIN" ]; then
  # Forward-slash Windows paths throughout: sed treats a backslash in the replacement
  # as an escape, and CreateProcess accepts either separator.
  BASH_WIN="$(cygpath -m "$(command -v bash)")"
  REPO_WIN="$(cygpath -m "$REPO")"
  HOME_WIN="$(cygpath -m "$HOME")"
  PY_WIN="$(cygpath -m "$PY")"
  TASKS="$(mktemp -d)"
  for l in $LABELS; do
    sed -e "s|__BASH__|$BASH_WIN|g" -e "s|__REPO_WIN__|$REPO_WIN|g" \
        -e "s|__HOME_WIN__|$HOME_WIN|g" -e "s|__VENV_PY_WIN__|$PY_WIN|g" \
        "$REPO/windows/$l.xml" > "$TASKS/$l.xml"
    powershell.exe -NoProfile -Command \
      "Register-ScheduledTask -TaskName '$l' -Xml (Get-Content -Raw '$(cygpath -w "$TASKS/$l.xml")') -Force" \
      >/dev/null
  done
else
  mkdir -p "$AGENTS"
  for l in $LABELS; do
    sed -e "s|__REPO__|$REPO|g" -e "s|__HOME__|$HOME|g" -e "s|__PYTHON__|$PY|g" \
      "$REPO/launchd/$l.plist" > "$AGENTS/$l.plist.new"
    # re-register only when the plist changed or isn't loaded: every bootstrap of a bash
    # agent fires a macOS "App Background Activity" popup
    if cmp -s "$AGENTS/$l.plist.new" "$AGENTS/$l.plist" && launchctl print "$DOMAIN/$l" >/dev/null 2>&1; then
      rm "$AGENTS/$l.plist.new"; continue
    fi
    mv "$AGENTS/$l.plist.new" "$AGENTS/$l.plist"
    launchctl bootout "$DOMAIN/$l" 2>/dev/null || true
    launchctl bootstrap "$DOMAIN" "$AGENTS/$l.plist"
  done
fi

echo "Installed. python: $PY3 | venv: $VENV | model: $MODEL_DIR"
echo "Hooks and permission rules merged into $SETTINGS"
echo "Skills in ~/.claude/skills, commands in ~/.claude/commands, logs in $LOGS"
echo "Schedules loaded:"
if [ -n "$WIN" ]; then
  for l in $LABELS; do schtasks /Query /TN "$l" /FO LIST 2>/dev/null | grep -i "TaskName\|Next Run" || echo "  $l: not registered"; done
else
  launchctl list | grep rekall || echo "  (none listed: run 'launchctl list | grep rekall' yourself)"
fi
echo "Undo everything: bash $REPO/install.sh --uninstall"
