# Hosted demo — runbook

The public demo lives at **https://intern-inbox-demo.fly.dev**. It is the real
app, running the real code, over **fifteen invented listings** from
[`automation/seed_demo.py`](../automation/seed_demo.py) — so someone can click
through the triage flow before deciding whether to install anything.

Only the owner deploys it. A normal install never touches any of this.

## No user data ever reaches it

This is the point of the demo mode, so it is worth being blunt about:

- The image is built from a context that **excludes** `config/career.toml`,
  `config/.env`, `data/`, `profile/`, and any `resume*` file — see
  [`.dockerignore`](../.dockerignore). The container starts from
  `config/career.example.toml`, the tracked defaults.
- Every row on the demo is invented. There is no IMAP account, no SMTP
  password, and no real posting.
- With `INTERN_INBOX_DEMO=1` set, four endpoints answer **403**: `POST
  /api/pull` (fetching from boards and email), `POST /api/email-saved` (sending
  mail), `POST /api/wizard/complete` (writing config), and `POST /api/add`
  (external ingestion). The 30-minute background auto-check does not start
  either, so the demo cannot reach out to the network at all.
- Status, note, and bulk stay **live** on purpose. Hearting and killing rows is
  the thing people came to try, and the hourly reset undoes it.

## Deploy (owner, three commands)

From the repo root, on a checkout with no uncommitted personal files.

1. **Install flyctl**

   ```bash
   brew install flyctl          # or: curl -L https://fly.io/install.sh | sh
   ```

2. **Sign in** (first time: `signup`, after that: `login`)

   ```bash
   fly auth signup              # or: fly auth login
   ```

3. **Create the app, then ship it**

   ```bash
   fly launch --copy-config --no-deploy
   fly deploy
   ```

   `--copy-config` makes `fly launch` adopt the tracked [`fly.toml`](../fly.toml)
   — app name `intern-inbox-demo`, region `ewr`, port 8477 — instead of writing
   a new one. `--no-deploy` keeps it from shipping before you have looked at
   what it decided. Later updates are just `fly deploy`.

## How the hourly reset works

[`automation/demo_entrypoint.sh`](../automation/demo_entrypoint.sh) is the
container's `CMD`. It copies `career.example.toml` into place if there is no
config, seeds once synchronously so the first visitor never sees an empty
table, then backgrounds a loop that every 3600 seconds deletes `data/inbox.db*`,
re-runs the migrations, and re-seeds the same fifteen rows. Then it `exec`s the
normal server on port 8477.

A cold start after scale-to-zero re-seeds too, since the machine comes up with a
fresh filesystem. Either way, whatever a visitor did is gone within the hour.

## Cost

`shared-cpu-1x` / 256 MB with `min_machines_running = 0` and
`auto_stop_machines = "stop"`: the machine sleeps when nobody is looking and
wakes on the next request. For demo-level traffic this lands at free-to-cents
per month. Watch it with `fly status` and `fly dashboard`.

## Tear down

```bash
fly apps destroy intern-inbox-demo
```

That removes the app, its machines, and its volumes. Nothing local is affected —
the demo never shared state with your own inbox.

## Running it locally

To see exactly what visitors see, without Docker:

```bash
INTERN_INBOX_DEMO=1 uv run intern-inbox --port 8478
```

Do this in a **scratch clone**, never your real checkout: `seed_demo.py` refuses
to run on a database that already has rows, but the demo entrypoint deletes
`data/inbox.db` before it seeds.
