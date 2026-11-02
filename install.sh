#!/bin/bash
# Rekall installer: every deterministic step of SETUP.md in one idempotent script.
# Run it after rekall.toml exists. Safe to re-run; `--uninstall` reverses
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
VENV="$REPO/graph-memory/.venv"
DOMAIN="gui/$(id -u)"
LABELS="com.rekall.fathom-pipeline com.rekall.wiki-lint com.rekall.wiki-reindex"
GRANOLA="com.rekall.granola-sweep"   # optional: --with-granola schedules it; --uninstall always removes it
case " $* " in *" --with-granola "*) LABELS="$LABELS $GRANOLA" ;; esac
GRAPH_INGEST="com.rekall.graph-ingest"  # optional, macOS only: --with-graph schedules it; --uninstall always removes it

case "$(uname -s)" in MINGW*|MSYS*|CYGWIN*) WIN=1 ;; *) WIN= ;; esac
case " $* " in *" --with-graph "*)
  if [ -n "$WIN" ]; then echo "--with-graph: the Graph ingest schedule is macOS-only; skipping it"
  else LABELS="$LABELS $GRAPH_INGEST"; fi ;;
esac
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

KEPT=()   # place() and unplace() lines for copies left alone, repeated at the end of the run

# 1. python 3.11+ (Apple's /usr/bin/python3 is too old, and python.org on Windows
# installs `python` rather than `python3`; prefer the newest one on PATH)
PY3=""
export PATH="$HOME/.local/bin:$PATH"   # uv-installed python and the claude CLI live here
for c in ${REKALL_PYTHON:-} python3.13 python3.12 python3.11 python3 python; do
  if command -v "$c" >/dev/null && "$c" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
    PY3="$(command -v "$c")"; break
  fi
done
[ -n "$PY3" ] || { echo "No python 3.11 or newer on PATH. Install one (brew install python, or python.org on Windows) and re-run." >&2; exit 1; }

# A test config would get rendered into files the scheduled jobs later read without it.
if [ -n "${REKALL_CONFIG+x}" ] && [ "$REKALL_CONFIG" != "$REPO/rekall.toml" ]; then
  echo "ignoring REKALL_CONFIG=$REKALL_CONFIG: install.sh always installs from $REPO/rekall.toml"
  unset REKALL_CONFIG
fi

# Prints the path of every clone a recall hook in settings.json names, once each (the current
# S="..." shape, and the older bare and $HOME-spelled ones). Nothing when settings.json is missing;
# exits 2 when it doesn't parse.
owner_paths() {
  [ -f "$SETTINGS" ] || return 0
  "$PY3" - "$SETTINGS" <<'EOF'
import json, os, re, sys
try:
    s = json.load(open(sys.argv[1]))
except ValueError:
    sys.exit(2)
seen = []
for g in s.get("hooks", {}).get("UserPromptSubmit", []):
    for h in g.get("hooks", []):
        # a quoted path may hold spaces; an unquoted one ends at whitespace, a quote, ; or =
        for q, bare in re.findall(r'"([^"]+)/graph-memory/recall_hook\.py"|([^"\s;=]+)/graph-memory/recall_hook\.py',
                                  h.get("command", "")):
            p = os.path.expanduser(os.path.expandvars(q or bare))
            if p not in seen:
                seen.append(p)
                print(p)
EOF
}

# One machine runs one install, owned by the clone the recall hook names. Writes nothing. Refuses
# when another clone still holds install.sh and rekall.toml (bootstrap.sh's test for an install);
# a dead owner's hook and schedules are replaced by the normal steps.
guard() {
  local me owners o
  # paths resolve in bash, so Git Bash's /c/... and Python's C:\... never meet in one comparison
  me="$(cd "$REPO" && pwd -P)"
  owners="$(owner_paths)" || { echo "can't read $SETTINGS; fix or move it, then re-run" >&2; return 1; }
  while IFS= read -r o; do
    o="${o%$'\r'}"  # Windows Python may end lines with CRLF
    [ -n "$o" ] || continue
    o="$(cd "$o" 2>/dev/null && pwd -P || echo "$o")"
    # -ef compares the folders themselves, so a path typed in another letter case is still this clone
    [ "$o" -ef "$me" ] && continue
    if [ -f "$o/install.sh" ] && [ -f "$o/rekall.toml" ]; then
      echo "Rekall is already installed from $o. One machine runs one install." >&2
      echo "To move it here: bash $o/install.sh --uninstall, then re-run this." >&2
      if [ "$(git -C "$REPO" rev-parse --git-dir 2>/dev/null)" != "$(git -C "$REPO" rev-parse --git-common-dir 2>/dev/null)" ]; then
        echo "This is a git worktree, which is expected to be refused. To test against another vault without installing, run scripts with REKALL_CONFIG=/path/to/test.toml." >&2
      fi
      return 1
    fi
    echo "taking over from $o, which no longer holds a Rekall install"
  done <<< "$owners"
  return 0
}
guard || exit 1

# Merges (or removes) rekall's hooks and permission rules in settings.json.
# Hooks match by script path and rules by exact string, so re-runs never duplicate.
settings() {  # $1 = add | remove, $2 = the state folder (fills __STATE__ in the recall hook's fallback log)
  mkdir -p "$(dirname "$SETTINGS")"
  [ -f "$SETTINGS" ] || echo '{}' > "$SETTINGS"
  "$PY3" - "$1" "$REPO" "$SETTINGS" "$PY" "$LIST_RULE" "$2" <<'EOF'
import json, re, sys
mode, repo, path, venv_py, list_rule, state = sys.argv[1:]
s = json.load(open(path))
ours = json.load(open(f"{repo}/hooks.json"))["hooks"]
hooks = s.setdefault("hooks", {})
for event, entries in ours.items():
    have = hooks.setdefault(event, [])
    for e in entries:
        e = json.loads(json.dumps(e).replace("__REPO__", repo).replace("__VENV_PY__", venv_py)
                       .replace("__STATE__", state))
        # match on the script path, so an older command shape for the same script is replaced, not kept beside
        # by the path inside the repo, so a hook spelled with $HOME or another clone's path is replaced too
        # ponytail: another tool's hook ending in the same graph-memory/... path would be replaced as well
        script = "/" + re.search(re.escape(repo) + r'/([^"]+\.py)', e["hooks"][0]["command"]).group(1)
        # entry level: our hook may sit beside another tool's in one group; drop a group only once it empties
        emptied = []
        for g in have:
            if any(script in x.get("command", "") for x in g.get("hooks", [])):
                g["hooks"] = [x for x in g["hooks"] if script not in x.get("command", "")]
                if not g["hooks"]:
                    emptied.append(g)
        have[:] = [g for g in have if not any(g is d for d in emptied)]
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

# Registers (or removes) the rekall MCP server in Claude Desktop's config, which has no
# UserPromptSubmit hook, so chat there reaches the wiki through graph-memory/mcp_server.py.
# Skipped when Claude Desktop isn't installed. Removal only touches an entry pointing at this repo.
desktop() {  # $1 = add | remove
  local cfg_dir py srv
  if [ -n "$WIN" ]; then
    cfg_dir="$(cygpath -u "${APPDATA:-}")/Claude"; py="$(cygpath -m "$PY")"; srv="$(cygpath -m "$REPO")/graph-memory/mcp_server.py"
  else
    cfg_dir="$HOME/Library/Application Support/Claude"; py="$PY"; srv="$REPO/graph-memory/mcp_server.py"
  fi
  [ -d "$cfg_dir" ] || { [ "$1" = add ] && echo "Claude Desktop not found ($cfg_dir); skipped MCP registration."; return 0; }
  "$PY3" - "$1" "$cfg_dir/claude_desktop_config.json" "$py" "$srv" <<'EOF'
import json, os, sys
mode, path, py, srv = sys.argv[1:]
c = json.load(open(path)) if os.path.exists(path) else {}
servers = c.setdefault("mcpServers", {})
if mode == "add":
    servers["rekall"] = {"command": py, "args": [srv]}
elif servers.get("rekall", {}).get("args") == [srv]:
    del servers["rekall"]
if not servers:
    del c["mcpServers"]
json.dump(c, open(path, "w"), indent=2)
open(path, "a").write("\n")
EOF
}

# The one substitution list (SUBST) every rendered skill, command, plist and task template goes
# through. A new placeholder goes here. Stops on a value that sed, the hook's JSON and shell quoting,
# or the XML can't carry.
subst_args() {
  local n v
  for n in REPO HOME PY STATE VAULT ${WIN:+BASH_WIN REPO_WIN HOME_WIN PY_WIN}; do
    v="${!n}"
    case "$v" in *[\|\&\"\\\'\<\$\`]*)
      echo "rekall.toml or the repo path contains a character install.sh can't write safely: $n=$v" >&2; exit 1 ;;
    esac
  done
  # a plain array: bash 3.2 on macOS has no associative arrays
  SUBST=(-e "s|__REPO__|$REPO|g" -e "s|__HOME__|$HOME|g" -e "s|__PYTHON__|$PY|g"
         -e "s|__STATE__|$STATE|g" -e "s|__VAULT__|$VAULT|g" -e "s|__VAULT_NAME__|$VAULT_NAME|g")
  if [ -n "$WIN" ]; then
    SUBST+=(-e "s|__BASH__|$BASH_WIN|g" -e "s|__REPO_WIN__|$REPO_WIN|g"
            -e "s|__HOME_WIN__|$HOME_WIN|g" -e "s|__VENV_PY_WIN__|$PY_WIN|g")
  fi
}

# Copies a skill dir or command file to a temp path, filled in through SUBST; prints the path.
render() {
  local out; out="$(mktemp -d)/$(basename "$1")"
  cp -R "$1" "$out"
  find "$out" -type f -exec sed "${SEDI[@]}" "${SUBST[@]}" {} +
  ! grep -rqE '__[A-Z_]+__' "$out" || { echo "a placeholder is left unsubstituted in $out" >&2; return 1; }
  echo "$out"
}

# Renders one template file through SUBST to $2 (a plist or a task XML).
render_file() {  # $1 = template, $2 = destination
  sed "${SUBST[@]}" "$1" > "$2"
  ! grep -qE '__[A-Z_]+__' "$2" || { echo "a placeholder is left unsubstituted in $2" >&2; return 1; }
}

# Places one skill or command at ~/.claude/<kind>/<name>. The record, $REPO/.installed/<kind>/<name>,
# is an exact copy of what this script last wrote there, so an untouched copy can be told from an
# edited one. First matching row wins: a symlink, a copy the user changed and a file rekall didn't
# write are left alone and named. Runs in the current shell (it appends to KEPT), never in $(...).
place() {  # $1 = $REPO/skills/<name> or $REPO/commands/<name>
  local kind name dst rec out said bak
  kind="$(basename "$(dirname "$1")")"; name="$(basename "$1")"
  dst="$HOME/.claude/$kind/$name"; rec="$REPO/.installed/$kind/$name"
  out="$(render "$1")" || exit 1
  if [ -L "$dst" ]; then said="left as is: $dst is a link"
  elif [ ! -e "$dst" ]; then
    mkdir -p "$(dirname "$dst")"; cp -R "$out" "$dst"; said="installed $dst"
  elif diff -rq "$out" "$dst" >/dev/null 2>&1; then said="unchanged $dst"
  elif [ -e "$rec" ] && diff -rq "$rec" "$dst" >/dev/null 2>&1; then
    rm -rf "$dst"; cp -R "$out" "$dst"; said="updated $dst"
  elif [ -e "$rec" ]; then said="kept $dst: you changed it"
  else said="left as is: $dst was not installed by rekall"
  fi
  echo "$said"
  case "$said" in
    installed*|unchanged*|updated*)
      # written right after its destination, so a record always equals what was last written
      rm -rf "$rec"; mkdir -p "$(dirname "$rec")"; cp -R "$out" "$rec" ;;
    *)
      # the backup goes under .installed/: a second folder in ~/.claude/skills/ would load as a second skill
      # a fresh name per run, so following the advice twice neither overwrites nor nests an earlier backup
      mkdir -p "$REPO/.installed/backup"
      bak="$(mktemp -u "$REPO/.installed/backup/$name.$(date +%Y%m%d-%H%M%S).XXXX")"
      echo "  to install the new version: mv $dst $bak && bash $REPO/install.sh"
      echo "  to compare afterwards: diff -ru $bak $dst"
      KEPT+=("$said") ;;
  esac
}

# Removes a placed copy only while it still equals its record; a link or an edited copy stays.
unplace() {  # $1 = as for place
  local kind name dst rec
  kind="$(basename "$(dirname "$1")")"; name="$(basename "$1")"
  dst="$HOME/.claude/$kind/$name"; rec="$REPO/.installed/$kind/$name"
  if [ -L "$dst" ]; then echo "left as is: $dst is a link"
  elif [ -e "$rec" ] && diff -rq "$rec" "$dst" >/dev/null 2>&1; then rm -rf "$dst" "$rec"
  elif [ -e "$dst" ]; then echo "kept $dst: you changed it"
  fi
}

uninstall() {
  LABELS="$LABELS $GRANOLA"
  [ -z "$WIN" ] && LABELS="$LABELS $GRAPH_INGEST"
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
  # the Documents shortcut, only if it is still the link this script made
  [ "$(readlink "$HOME/Documents/rekall" 2>/dev/null)" = "$HOME/rekall" ] && rm "$HOME/Documents/rekall"
  settings remove "$HOME/unused"   # removal matches on the script path, so the state value is unused
  desktop remove
  # only remove skills/commands that still match what this repo last wrote; an edited copy stays
  for src in "$REPO"/skills/* "$REPO"/commands/*; do unplace "$src"; done
  echo "Rekall uninstalled: schedules, hooks, skills, commands and the Claude Desktop MCP entry removed."
  echo "Kept: $REPO (with .venv and .env) and your wiki."
  exit 0
}
[ "${1:-}" = "--uninstall" ] && uninstall

# --standard (bootstrap.sh): write rekall.toml with the ~/rekall layout so nothing is asked in chat.
# The vault is picked on the setup page below; REKALL_VAULT presets it. Never overwrites a toml.
STANDARD= FRESH=
if [ -z "$WIN" ] && [ "${1:-}" = "--standard" ]; then
  STANDARD=1
  if [ ! -f "$REPO/rekall.toml" ]; then
    FRESH=1  # a new toml still needs its vault picked on the setup page
    tz="$(readlink /etc/localtime | sed 's|.*/zoneinfo/||')"
    name="$(id -F 2>/dev/null || id -un)"
    sed -e "s|^name = \"Your Name\"|name = \"$name\"|" -e "s|^timezone = \"America/Chicago\"|timezone = \"${tz:-America/Chicago}\"|" \
        -e "s|^path = \"~/rekall/vault\"|path = \"${REKALL_VAULT:-~/rekall/vault}\"|" \
      "$REPO/rekall.example.toml" > "$REPO/rekall.toml"
  fi
fi

[ -f "$REPO/rekall.toml" ] || { echo "rekall.toml is missing; write it first (SETUP.md step 3)." >&2; exit 1; }

# 3. venv, pinned packages, embedding model
[ -x "$PY" ] || "$PY3" -m venv "$VENV"
# Brings every package to its pin (a venv upgraded by hand goes back too); with every pin met, pip
# doesn't touch the network. tzdata is Windows-only: it ships no timezone database for zoneinfo.
"$PY" -m pip install -q -r "$REPO/graph-memory/requirements.txt" || {
  echo "pip couldn't install the pinned packages; if you're behind a corporate proxy, set up the CA bundle in SETUP.md, then re-run" >&2; exit 1; }
# --standard: the setup page collects the vault choice and the Fathom key, then closes itself.
# Opens for a new toml or missing keys, so a re-run of a finished install never reopens it.
if [ -n "$STANDARD" ]; then
  if [ -n "$FRESH" ] || ! "$PY" -c 'import sys; sys.path.insert(0, sys.argv[1]); import rekall_config as c; sys.exit(not (all(c.find_secret(k) for k in ("FATHOM_API_KEY", "WORK_EMAIL", "CLAUDE_CODE_OAUTH_TOKEN"))))' "$REPO"; then
    "$PY" "$REPO/scripts/setup-server.py" --once
  fi
  VAULT_DIR="$("$PY" "$REPO/rekall_config.py" VAULT)"
  if [ ! -e "$VAULT_DIR/wiki" ]; then
    mkdir -p "$VAULT_DIR"
    cp -R "$REPO/vault-template/." "$VAULT_DIR/"
    sed "${SEDI[@]}" "s|REKALL_REPO|$REPO|g" "$VAULT_DIR/wiki/CLAUDE.md"
  fi
  # Finder shortcut: ~/rekall lives outside Documents (privacy prompts, OneDrive/iCloud sync),
  # so link it from Documents where people look. A symlink, since a Finder alias needs osascript
  # and an Automation prompt. Only for the standard layout, and never over an existing entry.
  if [ "$REPO" = "$HOME/rekall/repo" ] && [ -d "$HOME/Documents" ] && [ ! -e "$HOME/Documents/rekall" ] && [ ! -L "$HOME/Documents/rekall" ]; then
    ln -s "$HOME/rekall" "$HOME/Documents/rekall"
  fi
fi
MODEL_DIR="$("$PY" "$REPO/rekall_config.py" DATA)/model"
[ -f "$MODEL_DIR/model_optimized.onnx" ] || PYTHON="$PY" bash "$REPO/graph-memory/fetch_model.sh"

# the values every rendered file gets (subst_args), all from rekall.toml
STATE="$("$PY" "$REPO/rekall_config.py" STATE_DIR)"
VAULT="$("$PY" "$REPO/rekall_config.py" VAULT)"
if [ -n "$WIN" ]; then
  # C:/... works in Git Bash, Python and the task XML alike, so one value serves every file
  STATE="$(cygpath -m "$STATE")"; VAULT="$(cygpath -m "$VAULT")"
fi
VAULT_NAME="$(basename "$VAULT")"   # Obsidian names a vault after its folder
LOGS="$STATE/logs"
if [ -n "$WIN" ]; then
  # Forward-slash Windows paths throughout: sed treats a backslash in the replacement
  # as an escape, and CreateProcess accepts either separator.
  BASH_WIN="$(cygpath -m "$(command -v bash)")"
  REPO_WIN="$(cygpath -m "$REPO")"
  HOME_WIN="$(cygpath -m "$HOME")"
  PY_WIN="$(cygpath -m "$PY")"
fi
subst_args

# 4. hooks + permission rules
settings add "$STATE"

# 5. skills and commands: refreshed unless you changed the copy or rekall didn't write it
for src in "$REPO"/skills/* "$REPO"/commands/*; do place "$src"; done

# 6. MCP server for Claude Desktop
desktop add

# 7. schedules
# A hand-made agent under another label that runs the same script would run the job twice
# (two ingests racing, two lints). Prints that plist and returns 0 if there is one.
scheduled_elsewhere() {  # $1 = label; reads $AGENTS/$1.plist.new
  local script f
  script="$(grep -o "$REPO/[^<]*" "$AGENTS/$1.plist.new" | head -1)"
  for f in "$AGENTS"/*.plist; do
    [ -f "$f" ] && [ "$f" != "$AGENTS/$1.plist" ] && grep -qF "$script" "$f" && { echo "$f"; return 0; }
  done
  return 1
}
mkdir -p "$LOGS"
if [ -n "$WIN" ]; then
  TASKS="$(mktemp -d)"
  for l in $LABELS; do
    render_file "$REPO/windows/$l.xml" "$TASKS/$l.xml" || exit 1
    powershell.exe -NoProfile -Command \
      "Register-ScheduledTask -TaskName '$l' -Xml (Get-Content -Raw '$(cygpath -w "$TASKS/$l.xml")') -Force" \
      >/dev/null
  done
else
  mkdir -p "$AGENTS"
  for l in $LABELS; do
    render_file "$REPO/launchd/$l.plist" "$AGENTS/$l.plist.new" || exit 1
    if other="$(scheduled_elsewhere "$l")"; then
      echo "skipping $l: $other already runs it. To move onto $l: launchctl bootout $DOMAIN/$(basename "$other" .plist), move $other out of $AGENTS, then re-run install.sh"
      rm "$AGENTS/$l.plist.new"; continue
    fi
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
echo "MCP server 'rekall' registered for Claude Desktop (if installed); restart Claude Desktop to load it"
echo "Schedules loaded:"
if [ -n "$WIN" ]; then
  for l in $LABELS; do schtasks /Query /TN "$l" /FO LIST 2>/dev/null | grep -i "TaskName\|Next Run" || echo "  $l: not registered"; done
else
  launchctl list | grep rekall || echo "  (none listed: run 'launchctl list | grep rekall' yourself)"
fi
if [ ${#KEPT[@]} -gt 0 ]; then
  echo "Left alone (the lines above say how to install the new version):"
  for k in "${KEPT[@]}"; do echo "  $k"; done
fi
# Warns (never fails the install) when a headless Claude call doesn't answer, i.e. nobody has signed in.
"$PY" "$REPO/scripts/setup-server.py" --probe || true
# --standard on a new install: pull the last 30 days of meetings now instead of waiting for the hourly
# run, which only looks back 26 hours. nohup, so closing Terminal doesn't stop it; the pipeline's
# own lock keeps the hourly job from running beside it.
if [ -n "$FRESH" ]; then
  nohup bash "$REPO/scripts/run-fathom-pipeline.sh" --since "$(date -v-30d +%F)" --no-monday \
    >> "$LOGS/backfill.log" 2>&1 &
  echo "Backfill of the last 30 days started in the background (about an hour). Progress: $LOGS/backfill.log"
fi
echo "Undo everything: bash $REPO/install.sh --uninstall"
