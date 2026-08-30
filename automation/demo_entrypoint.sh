#!/bin/sh
# Entrypoint for the hosted demo (intern-inbox-demo.fly.dev) ONLY.
#
# The demo runs the real app over invented rows from automation/seed_demo.py and
# wipes itself every hour, so anything visitors do — hearting, killing, notes —
# is gone within the hour and no real listing or personal data is ever involved.
# INTERN_INBOX_DEMO=1 and INTERN_INBOX_HOST=0.0.0.0 come from the Dockerfile.
#
# Never run this against a real checkout: it deletes data/inbox.db.
set -e
cd "$(dirname "$0")/.."

# The demo image ships without config/career.toml (.dockerignore'd), so the app
# would otherwise bounce to the setup wizard. Seed the tracked example instead.
[ -f config/career.toml ] || cp config/career.example.toml config/career.toml

reseed() {
  rm -f data/inbox.db data/inbox.db-wal data/inbox.db-shm
  uv run python -c "import db; db.migrate()" \
    && uv run python automation/seed_demo.py
}

# One synchronous seed so the first visitor never lands on an empty table.
reseed

# Hourly reset, in the background, for the life of the container.
while true; do
  sleep 3600
  reseed || echo "demo reseed failed; leaving the current database in place" >&2
done &

exec uv run intern-inbox --port 8477
