"""THE write surface of career-inbox. CLAUDE.md contract: this module may UPDATE
exactly opportunities.status / applied_date / notes — and, since migration 007,
APPEND stage_events (on every real status change), contact_events (manual log),
company_domains (user add + accept-time learning), and resolve suggestions.
Nothing else, ever. The mail-scan feed never calls in here; a suggestion only
becomes a status change when the user accepts it (accept_suggestion)."""
from datetime import date, datetime

import db

VALID_STATUSES = ("new", "shortlisted", "applied", "interviewing",
                  "offer", "rejected", "dead")
VALID_SOURCES = ("ui", "skill", "mail-confirm")
BULK_ACTIONS = {"kill": "dead", "shortlist": "shortlisted"}
KIND_TO_STATUS = {"set_applied": "applied", "set_interviewing": "interviewing",
                  "set_offer": "offer", "set_rejected": "rejected"}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _fetch(conn, job_id):
    row = conn.execute("SELECT * FROM opportunities WHERE id=?", (job_id,)).fetchone()
    if row is None:
        raise ValueError(f"no opportunity with id {job_id}")
    return dict(row)


def _append_event(conn, job_id, from_status, to_status, *, source, note=None,
                  suggestion_id=None, occurred_at=None):
    conn.execute(
        "INSERT INTO stage_events (opportunity_id, from_status, to_status, "
        "occurred_at, source, note, suggestion_id) VALUES (?,?,?,?,?,?,?)",
        (job_id, from_status, to_status, occurred_at or _now(), source, note,
         suggestion_id))


def set_status(job_id: int, status: str, *, source: str = "ui", note: str = None,
               suggestion_id: int = None, occurred_at: str = None,
               applied_on: str = None) -> dict:
    """Change a row's status and append the stage event in the same transaction.
    No event on a no-op (idempotent clicks stay silent). applied_on lets a
    mail-confirm stamp applied_date with the evidence date instead of today —
    only on the first transition to 'applied' (an existing date is sacred)."""
    if status not in VALID_STATUSES:
        raise ValueError(f"invalid status {status!r}")
    if source not in VALID_SOURCES:
        raise ValueError(f"invalid source {source!r}")
    conn = db.connect()
    try:
        row = _fetch(conn, job_id)
        if status == "applied" and not row["applied_date"]:
            conn.execute("UPDATE opportunities SET status=?, applied_date=? WHERE id=?",
                         (status, applied_on or date.today().isoformat(), job_id))
        else:
            conn.execute("UPDATE opportunities SET status=? WHERE id=?", (status, job_id))
        if row["status"] != status:
            _append_event(conn, job_id, row["status"], status, source=source,
                          note=note, suggestion_id=suggestion_id,
                          occurred_at=occurred_at)
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


def bulk(ids: list, action: str, *, source: str = "ui") -> int:
    """Per-id loop (one connection) so stage events append per changed row.
    Return value keeps the pre-007 semantics: count of EXISTING ids touched."""
    if action not in BULK_ACTIONS:
        raise ValueError(f"invalid bulk action {action!r}")
    if not ids:
        return 0
    status = BULK_ACTIONS[action]
    conn = db.connect()
    try:
        n = 0
        for job_id in ids:
            row = conn.execute("SELECT id, status FROM opportunities WHERE id=?",
                               (job_id,)).fetchone()
            if row is None:
                continue
            n += 1
            if row["status"] == status:
                continue
            conn.execute("UPDATE opportunities SET status=? WHERE id=?",
                         (status, job_id))
            _append_event(conn, job_id, row["status"], status, source=source)
        conn.commit()
        return n
    finally:
        conn.close()


def log_contact(*, opportunity_id: int = None, company_id: int = None,
                direction: str, occurred_at: str = None, subject: str = None,
                note: str = None) -> dict:
    """Manual touch log — the user's own 'contacted them today' record."""
    if direction not in ("out", "in"):
        raise ValueError(f"invalid direction {direction!r}")
    if opportunity_id is None and company_id is None:
        raise ValueError("log_contact needs an opportunity_id or a company_id")
    conn = db.connect()
    try:
        if opportunity_id is not None:
            row = _fetch(conn, opportunity_id)
            company_id = company_id or row["company_id"]
        cur = conn.execute(
            "INSERT INTO contact_events (company_id, opportunity_id, direction, "
            "channel, occurred_at, subject, snippet, created_by, created_at) "
            "VALUES (?,?,?,'manual',?,?,?,'user',?)",
            (company_id, opportunity_id, direction, occurred_at or _now(),
             subject, (note or "").strip()[:200] or None, _now()))
        conn.commit()
        row = dict(conn.execute("SELECT * FROM contact_events WHERE id=?",
                                (cur.lastrowid,)).fetchone())
        return {"contact": row}
    finally:
        conn.close()


def _get_open_suggestion(conn, sug_id):
    row = conn.execute("SELECT * FROM suggestions WHERE id=?", (sug_id,)).fetchone()
    if row is None:
        raise ValueError(f"no suggestion with id {sug_id}")
    sug = dict(row)
    if sug["status"] != "open":
        raise ValueError(f"suggestion {sug_id} is already {sug['status']}")
    return sug


def _learn_domain(conn, sug, msg, job) -> None:
    """Accepting IS the user's confirmation that the sender belongs to this
    company — learn its domain unless it's a shared ATS/board/freemail host."""
    from career_hunt.mail_classify import is_blocked, registrable_domain
    dom = registrable_domain(msg.get("from_addr") or "")
    cid = sug.get("company_id") or job.get("company_id")
    if not dom or not cid or is_blocked(dom):
        return
    conn.execute("INSERT OR IGNORE INTO company_domains (company_id, domain, "
                 "source, created_at) VALUES (?,?,'learned',?)", (cid, dom, _now()))


def accept_suggestion(sug_id: int) -> dict:
    """Apply a mail-scan suggestion: the ONLY path from email evidence to a
    status change. Two transactions on purpose — a crash between them leaves an
    open suggestion whose re-accept is a harmless no-op transition."""
    conn = db.connect()
    try:
        sug = _get_open_suggestion(conn, sug_id)
        msg = {}
        if sug["email_message_id"]:
            m = conn.execute("SELECT * FROM email_messages WHERE id=?",
                             (sug["email_message_id"],)).fetchone()
            msg = dict(m) if m else {}
    finally:
        conn.close()
    sent = msg.get("sent_at")
    job = set_status(sug["opportunity_id"], KIND_TO_STATUS[sug["kind"]],
                     source="mail-confirm", suggestion_id=sug_id, occurred_at=sent,
                     applied_on=(sent or "")[:10] or None)
    conn = db.connect()
    try:
        conn.execute("UPDATE suggestions SET status='accepted', resolved_at=? "
                     "WHERE id=?", (_now(), sug_id))
        _learn_domain(conn, sug, msg, job)
        conn.commit()
        sug = dict(conn.execute("SELECT * FROM suggestions WHERE id=?",
                                (sug_id,)).fetchone())
        return {"job": job, "suggestion": sug}
    finally:
        conn.close()


def dismiss_suggestion(sug_id: int) -> dict:
    conn = db.connect()
    try:
        _get_open_suggestion(conn, sug_id)
        conn.execute("UPDATE suggestions SET status='dismissed', resolved_at=? "
                     "WHERE id=?", (_now(), sug_id))
        conn.commit()
        return {"suggestion": dict(conn.execute(
            "SELECT * FROM suggestions WHERE id=?", (sug_id,)).fetchone())}
    finally:
        conn.close()


def add_company_domain(company_id: int, domain: str) -> dict:
    """The manual 'this is their mail domain' affordance — what makes the Sent
    scan work for companies whose website was never enriched."""
    from career_hunt.mail_classify import is_blocked, registrable_domain
    dom = registrable_domain(domain or "")
    if not dom:
        raise ValueError("that doesn't look like a domain")
    if is_blocked(dom):
        raise ValueError(f"'{dom}' is a shared job-board/mail host, not a company domain")
    conn = db.connect()
    try:
        if conn.execute("SELECT 1 FROM companies WHERE id=?",
                        (company_id,)).fetchone() is None:
            raise ValueError(f"no company with id {company_id}")
        conn.execute("INSERT OR IGNORE INTO company_domains (company_id, domain, "
                     "source, created_at) VALUES (?,?,'user',?)",
                     (company_id, dom, _now()))
        conn.commit()
        return {"company_id": company_id, "domain": dom}
    finally:
        conn.close()
