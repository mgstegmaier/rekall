#!/bin/bash
# One-command Rekall install for macOS:
#   curl -fsSL https://raw.githubusercontent.com/mgstegmaier/rekall/main/bootstrap.sh | bash
# Installs what's missing (git, Python 3.13 via uv, the Claude Code CLI) without asking for
# an admin password, clones the repo to ~/rekall/repo, and hands off to install.sh --standard.
# Safe to re-run: each step skips itself when its result is already there.
set -euo pipefail

REPO="$HOME/rekall/repo"
export PATH="$HOME/.local/bin:$PATH"   # where uv, uv's python and claude install

[ "$(uname -s)" = Darwin ] || { echo "bootstrap.sh is macOS-only; on Windows follow SETUP.md." >&2; exit 1; }

# git ships with the Command Line Tools; this is the one system dialog in the install
if ! xcode-select -p >/dev/null 2>&1; then
  echo "Installing Apple's Command Line Tools (for git). Click Install in the dialog that opens."
  xcode-select --install || true
  until xcode-select -p >/dev/null 2>&1; do /bin/sleep 5; done
fi

command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh
uv python install 3.13
REKALL_PYTHON="$(uv python find 3.13)"
export REKALL_PYTHON   # install.sh tries this before searching PATH

command -v claude >/dev/null || curl -fsSL https://claude.ai/install.sh | bash

if [ -d "$REPO/.git" ]; then
  git -C "$REPO" pull --ff-only
else
  mkdir -p "$(dirname "$REPO")"
  git clone https://github.com/mgstegmaier/rekall "$REPO"
fi

exec bash "$REPO/install.sh" --standard
