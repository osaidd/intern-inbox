#!/bin/sh
# intern-inbox bootstrap — one command from a fresh Mac (or Linux) to ready-to-/setup.
#   curl -LsSf https://raw.githubusercontent.com/osaidd/intern-inbox/main/bootstrap.sh | sh
# Installs uv if missing, clones (or updates) the repo into ~/intern-inbox,
# installs dependencies, then tells you the two remaining steps.
set -e

if ! command -v git >/dev/null 2>&1; then
  if [ "$(uname)" = "Darwin" ]; then
    echo "git is missing — opening Apple's installer for you now."
    echo "Click Install, wait for it to finish, then paste this command again."
    xcode-select --install >/dev/null 2>&1 || true
  else
    echo "git is missing — install it with your package manager, then re-run."
  fi
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
echo "Installing dependencies (well under a minute on a normal connection)..."
uv sync

# zero-friction handoff: Claude Code if it's here, otherwise straight into the app
if command -v claude >/dev/null 2>&1; then
  printf '\nFound Claude Code — opening the project in it now. Type /setup when it loads.\n'
  cd "$DIR" && exec claude
fi
printf '\nStarting Intern Inbox — your browser will open with a 3-step setup.\n'
printf 'To stop: Ctrl+C.  To start again later:  cd %s && uv run intern-inbox --open\n\n' "$DIR"
cd "$DIR" && exec uv run intern-inbox --open
