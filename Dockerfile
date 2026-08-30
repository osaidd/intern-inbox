# Image for the PUBLIC DEMO ONLY (intern-inbox-demo.fly.dev) — see docs/DEMO.md.
# A normal install is `uv run intern-inbox`; nothing here is needed for that, and
# no personal file ever enters this image (see .dockerignore).
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app
COPY . .
RUN uv sync --frozen --no-dev

# The two UV_ vars matter: `uv run` re-syncs the environment before it runs, so
# without them the entrypoint would try to re-resolve the lockfile AND install
# the dev group (pytest, httpx) at container start — network the demo box may
# not have. With them, the env built above already matches and the sync is a
# no-op. Verified locally: a clean `uv sync --frozen --no-dev` followed by the
# entrypoint prints no install line at all.
ENV INTERN_INBOX_DEMO=1 \
    INTERN_INBOX_HOST=0.0.0.0 \
    UV_FROZEN=1 \
    UV_NO_DEV=1

EXPOSE 8477
CMD ["sh", "automation/demo_entrypoint.sh"]
