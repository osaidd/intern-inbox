# Image for the PUBLIC DEMO ONLY (intern-inbox-demo.fly.dev) — see docs/DEMO.md.
# A normal install is `uv run intern-inbox`; nothing here is needed for that, and
# no personal file ever enters this image (see .dockerignore).
# Python 3.14 on purpose: uv.lock is generated and CI-tested on 3.14, and the
# build below runs `uv sync --frozen`, which forbids re-resolving. Building on a
# different interpreter is how you get a lockfile that cannot be satisfied.
FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim

WORKDIR /app
COPY . .
RUN uv sync --frozen --no-dev

# Nothing in the demo needs root. The entrypoint writes only inside /app --
# config/career.toml and data/inbox.db -- so /app changes hands. data/ is made
# here rather than left to db.migrate() so it is owned by demo from the start.
# HOME is explicit: Docker keeps /root across a USER switch, and uv would then
# try to write its cache somewhere this user cannot.
RUN useradd --create-home --uid 10001 demo \
    && mkdir -p /app/data \
    && chown -R demo:demo /app /home/demo
USER demo
ENV HOME=/home/demo

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
