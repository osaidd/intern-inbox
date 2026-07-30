#!/bin/sh
# intern-inbox bootstrap — one command from a fresh Mac (or Linux) to ready-to-/setup.
#   curl -LsSf https://raw.githubusercontent.com/osaidd/intern-inbox/main/bootstrap.sh | sh
# Installs uv if missing, clones (or updates) the repo into ~/intern-inbox,
# installs dependencies, then tells you the two remaining steps.
set -e

if ! command -v git >/dev/null 2>&1; then
  echo "git is missing. On a Mac, run:  xcode-select --install"
  echo "then re-run this command once that finishes."
  exit 1
fi

if ! command -v uv >/dev/null 2>&1 && [ ! -x "$HOME/.local/bin/uv" ]; then
  echo "Installing uv (the Python tool this project uses)..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
export PATH="$HOME/.local/bin:$PATH"

DIR="$HOME/intern-inbox"
if [ -d "$DIR/.git" ]; then
  echo "Already cloned at $DIR — pulling updates."
  git -C "$DIR" pull --ff-only
else
  git clone https://github.com/osaidd/intern-inbox.git "$DIR"
fi

cd "$DIR"
echo "Installing dependencies (a few minutes the first time)..."
uv sync

printf '\nAll set. Two steps left:\n'
printf '  1. Open the folder  %s  in Claude Code\n' "$DIR"
printf '  2. Type  /setup  and follow the conversation\n'
