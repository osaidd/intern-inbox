"""Entry point: uv run intern-inbox [--port 8477]."""
import argparse


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8477)
    a = ap.parse_args()
    import uvicorn
    from career_inbox.web import app     # also puts the repo root on sys.path
    import db
    from feeds.envfile import load_env
    load_env()
    db.migrate()                         # first launch may predate /setup; no-op when current
    uvicorn.run(app, host="127.0.0.1", port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
