"""THE write surface of career-inbox. CLAUDE.md contract: this module may UPDATE
exactly opportunities.status / applied_date / notes. Nothing else, ever."""
from datetime import date

import db

VALID_STATUSES = ("new", "shortlisted", "applied", "interviewing",
                  "offer", "rejected", "dead")
BULK_ACTIONS = {"kill": "dead", "shortlist": "shortlisted"}


def _fetch(conn, job_id):
    row = conn.execute("SELECT * FROM opportunities WHERE id=?", (job_id,)).fetchone()
    if row is None:
        raise ValueError(f"no opportunity with id {job_id}")
    return dict(row)


def set_status(job_id: int, status: str) -> dict:
    if status not in VALID_STATUSES:
        raise ValueError(f"invalid status {status!r}")
    conn = db.connect()
    try:
        row = _fetch(conn, job_id)
        if status == "applied" and not row["applied_date"]:
            conn.execute("UPDATE opportunities SET status=?, applied_date=? WHERE id=?",
                         (status, date.today().isoformat(), job_id))
        else:
            conn.execute("UPDATE opportunities SET status=? WHERE id=?", (status, job_id))
        conn.commit()
        return _fetch(conn, job_id)
    finally:
        conn.close()


def set_note(job_id: int, text: str) -> dict:
    conn = db.connect()
    try:
        _fetch(conn, job_id)
        conn.execute("UPDATE opportunities SET notes=? WHERE id=?",
                     (text.strip() or None, job_id))
        conn.commit()
        return _fetch(conn, job_id)
    finally:
        conn.close()


def bulk(ids: list, action: str) -> int:
    if action not in BULK_ACTIONS:
        raise ValueError(f"invalid bulk action {action!r}")
    if not ids:
        return 0
    status = BULK_ACTIONS[action]
    conn = db.connect()
    try:
        marks = ",".join("?" for _ in ids)
        cur = conn.execute(
            f"UPDATE opportunities SET status=? WHERE id IN ({marks})", (status, *ids))
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()
