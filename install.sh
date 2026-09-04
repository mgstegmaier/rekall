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
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETTINGS="$HOME/.claude/settings.json"
AGENTS="$HOME/Library/LaunchAgents"
LOGS="$HOME/.config/rekall/logs"
VENV="$REPO/graph-memory/.venv"
PY="$VENV/bin/python"
DOMAIN="gui/$(id -u)"
LABELS="com.rekall.fathom-pipeline com.rekall.wiki-lint com.rekall.wiki-reindex"

# Merges (or removes) rekall's hooks and permission rules in settings.json.
# Matching is by exact command / rule string, so re-runs never duplicate.
settings() {  # $1 = add | remove
  mkdir -p "$(dirname "$SETTINGS")"
  [ -f "$SETTINGS" ] || echo '{}' > "$SETTINGS"
  python3 - "$1" "$REPO" "$SETTINGS" <<'EOF'
import json, sys
mode, repo, path = sys.argv[1:]
s = json.load(open(path))
ours = json.load(open(f"{repo}/hooks.json"))["hooks"]
hooks = s.setdefault("hooks", {})
for event, entries in ours.items():
    have = hooks.setdefault(event, [])
    for e in entries:
        e = json.loads(json.dumps(e).replace("__REPO__", repo))
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
rules = ["Bash(launchctl list:*)", f"Read({path})"]
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
  find "$out" -type f -exec sed -i '' "s|__REPO__|$REPO|g" {} +
  echo "$out"
}

uninstall() {
  for l in $LABELS; do
    launchctl bootout "$DOMAIN/$l" 2>/dev/null || true
    rm -f "$AGENTS/$l.plist"
  done
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

# 1. python 3.11+ (Apple's /usr/bin/python3 is too old; prefer a newer one on PATH)
PY3=""
for c in python3.13 python3.12 python3.11 python3; do
  if command -v "$c" >/dev/null && "$c" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
    PY3="$(command -v "$c")"; break
  fi
done
[ -n "$PY3" ] || { echo "No python3 3.11 or newer on PATH. Install one (brew install python) and re-run." >&2; exit 1; }

# 2. secrets skeleton (values are yours to fill in; never overwritten)
[ -f "$REPO/.env" ] || cp "$REPO/.env.example" "$REPO/.env"
chmod 600 "$REPO/.env"

# 3. venv, fastembed, embedding model
[ -x "$PY" ] || "$PY3" -m venv "$VENV"
"$PY" -c 'import fastembed' 2>/dev/null || "$PY" -m pip install -q fastembed
export PATH="$VENV/bin:$PATH"   # fetch_model.sh and rekall_config.py want a 3.11+ python3
MODEL_DIR="$(python3 "$REPO/rekall_config.py" DATA)/model"
[ -f "$MODEL_DIR/model_optimized.onnx" ] || bash "$REPO/graph-memory/fetch_model.sh"

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
mkdir -p "$AGENTS" "$LOGS"
for l in $LABELS; do
  sed -e "s|__REPO__|$REPO|g" -e "s|__HOME__|$HOME|g" -e "s|__PYTHON__|$PY|g" \
    "$REPO/launchd/$l.plist" > "$AGENTS/$l.plist"
  launchctl bootout "$DOMAIN/$l" 2>/dev/null || true
  launchctl bootstrap "$DOMAIN" "$AGENTS/$l.plist"
done

echo "Installed. python: $PY3 | venv: $VENV | model: $MODEL_DIR"
echo "Hooks and permission rules merged into $SETTINGS"
echo "Skills in ~/.claude/skills, commands in ~/.claude/commands, logs in $LOGS"
echo "Schedules loaded:"
launchctl list | grep rekall || echo "  (none listed: run 'launchctl list | grep rekall' yourself)"
echo "Undo everything: bash $REPO/install.sh --uninstall"
