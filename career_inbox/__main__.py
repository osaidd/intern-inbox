"""Entry point: uv run intern-inbox [--port 8477] [--open]."""
import argparse
import os


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8477)
    ap.add_argument("--open", action="store_true",
                    help="open the browser once the server is up")
    a = ap.parse_args()
    import uvicorn
    from career_inbox.web import app     # also puts the repo root on sys.path
    import db
    from feeds.envfile import load_env
    load_env()
    db.migrate()                         # first launch may predate /setup; no-op when current
    if a.open:
        import threading
        import webbrowser
        threading.Timer(1.2, lambda: webbrowser.open(
            f"http://127.0.0.1:{a.port}")).start()
    # localhost by default — the only container that widens this is the hosted
    # demo, whose Dockerfile sets INTERN_INBOX_HOST=0.0.0.0.
    host = os.environ.get("INTERN_INBOX_HOST", "127.0.0.1")
    uvicorn.run(app, host=host, port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
