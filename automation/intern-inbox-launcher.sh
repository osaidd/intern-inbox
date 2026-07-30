#!/bin/zsh
# macOS extra — optional.
# "Intern Inbox.app" entry point. Starts the intern-inbox server if nothing is
# already listening on the port, then opens it in your browser.
# Unsigned shell apps sometimes launch as x86_64; force arm64 so the venv's
# native wheels load.
if [[ "$(uname -m)" != "arm64" ]]; then exec arch -arm64 /bin/zsh "$0" "$@"; fi
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PORT=8477
# Finder gives an app almost no PATH, so probe the known install locations first.
UV="$HOME/.local/bin/uv"
[[ -x "$UV" ]] || UV="/opt/homebrew/bin/uv"
[[ -x "$UV" ]] || UV="$(command -v uv)"
LOGS="$HOME/.intern-inbox/logs"
mkdir -p "$LOGS"
if ! lsof -iTCP:$PORT -sTCP:LISTEN >/dev/null 2>&1; then
  cd "$REPO" || exit 1
  nohup "$UV" run intern-inbox \
    >> "$LOGS/intern-inbox-$(date +%Y-%m-%d).log" 2>&1 &
  for _ in {1..40}; do
    lsof -iTCP:$PORT -sTCP:LISTEN >/dev/null 2>&1 && break
    sleep 0.25
  done
fi
open "http://127.0.0.1:$PORT"
