"""Single shared DB helper for intern-inbox. ALL database access goes through this module."""
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "data" / "inbox.db"
MIGRATIONS_DIR = ROOT / "migrations"


def _normalize_ts(ts):
    """Normalize ISO timestamps to naive LOCAL time ('YYYY-MM-DDTHH:MM:SS').
    UTC 'Z'/offset-suffixed values are converted to local; naive values pass through."""
    if not isinstance(ts, str) or not ts:
        return ts
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return ts
    if dt.tzinfo is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    return dt.isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def connect_ro() -> sqlite3.Connection:
    """Read-only connection (URI mode=ro): rejects writes at the SQLite level
    and never creates the DB file — raises OperationalError if it is missing."""
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    return conn


def migrate() -> list:
    """Apply pending migrations/*.sql in name order. Returns names applied this call."""
    conn = connect()
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "name TEXT PRIMARY KEY, "
            "applied_at TEXT NOT NULL DEFAULT (datetime('now')))"
        )
        done = {r["name"] for r in conn.execute("SELECT name FROM schema_migrations")}
        applied = []
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if path.name in done:
                continue
            # executescript() commits any pending transaction BEFORE running the
            # script; the leading "BEGIN;" keeps the script's DDL inside an open
            # transaction that the bookkeeping INSERT below joins, so commit()
            # lands both atomically. Constraint: migration files must NOT contain
            # their own BEGIN/COMMIT.
            conn.executescript("BEGIN;\n" + path.read_text())
            conn.execute("INSERT INTO schema_migrations (name) VALUES (?)", (path.name,))
            conn.commit()
            applied.append(path.name)
        return applied
    finally:
        conn.close()


def insert(table: str, row: dict) -> int:
    if not table.isidentifier() or not all(k.isidentifier() for k in row):
        raise ValueError(f"invalid identifier in insert({table!r}, {list(row)})")
    cols = ", ".join(row)
    marks = ", ".join("?" for _ in row)
    conn = connect()
    try:
        cur = conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", tuple(row.values()))
        conn.commit()
        rowid = cur.lastrowid
        return rowid
    finally:
        conn.close()


def log_run(skill, trigger, status, summary, started_at,
            finished_at=None, output_path=None, metrics_json=None) -> int:
    return insert("run_log", {
        "skill": skill, "trigger": trigger, "status": status, "summary": summary,
        "started_at": _normalize_ts(started_at), "finished_at": _normalize_ts(finished_at),
        "output_path": output_path, "metrics_json": metrics_json,
    })


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "migrate":
        names = migrate()
        print(f"applied: {names}" if names else "up to date")
    else:
        print("usage: python db.py migrate")
