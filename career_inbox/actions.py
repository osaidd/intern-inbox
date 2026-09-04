"""THE write surface of career-inbox. CLAUDE.md contract: this module may UPDATE
opportunities.status / applied_date / notes / next_action_* — plus, via
edit_job, the user-correctable row fields (company/role/url/location/
salary_text/posted_date and their derived dedupe_hash/company_id/work_mode/
priority/score) — and APPEND stage_events (on every real status change),
contact_events (manual log), company_domains (user add + accept-time learning),
and resolve suggestions. Nothing else, ever. The mail-scan feed never calls in
here; a suggestion only becomes a status change when the user accepts it."""
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


EDITABLE_FIELDS = ("company", "role", "url", "location", "salary_text",
                   "posted_date")


def edit_job(job_id: int, fields: dict) -> dict:
    """User corrections to a row. Identity edits (company/role/url) recompute
    dedupe_hash — colliding with another row raises instead of silently forking
    — relink the company row, and refresh work_mode/priority/score so the
    ranking stays honest. An edit never auto-buries a row (dead tier -> low)."""
    from career_hunt import config as ch_config
    from career_hunt.models import Job, dedupe_hash
    from career_hunt.score import detect_work_mode
    from career_hunt.score import priority as priority_fn
    from career_hunt.store import get_or_create_company
    from feeds.jobspy_pull import load_config as load_legacy_config
    from feeds.jobspy_pull import score_job

    unknown = set(fields) - set(EDITABLE_FIELDS)
    if unknown:
        raise ValueError(f"not editable: {', '.join(sorted(unknown))}")
    if not fields:
        raise ValueError("nothing to edit")
    clean = {k: ((v or "").strip() or None) if isinstance(v, str) or v is None
             else str(v).strip() or None for k, v in fields.items()}
    conn = db.connect()
    try:
        row = _fetch(conn, job_id)
        merged = {k: (clean[k] if k in clean else row[k]) for k in EDITABLE_FIELDS}
        if not merged["company"] or not merged["role"]:
            raise ValueError("company and role can't be blank")
        if merged["url"] and not merged["url"].lower().startswith(
                ("http://", "https://")):
            raise ValueError("url must start with http(s)://")
        if merged["posted_date"]:
            merged["posted_date"] = merged["posted_date"][:10]
            try:
                date.fromisoformat(merged["posted_date"])
            except ValueError:
                raise ValueError("posted_date must be YYYY-MM-DD")
        new_hash = dedupe_hash(merged["company"], merged["role"], merged["url"])
        dup = conn.execute("SELECT id FROM opportunities WHERE dedupe_hash=? "
                           "AND id != ?", (new_hash, job_id)).fetchone()
        if dup:
            raise ValueError(f"already tracked as row {dup['id']}")
        company_id = row["company_id"]
        if merged["company"] != row["company"] or company_id is None:
            company_id = get_or_create_company(conn, merged["company"])
        comp = None
        if company_id:
            c = conn.execute("SELECT stage, headcount FROM companies WHERE id=?",
                             (company_id,)).fetchone()
            comp = dict(c) if c else None
        cfg = ch_config.load()
        job = Job(company=merged["company"], role=merged["role"],
                  url=merged["url"], location=merged["location"],
                  jd_text=row["jd_text"], posted_date=merged["posted_date"],
                  salary_text=merged["salary_text"])
        pri = priority_fn(job, comp, cfg)
        conn.execute(
            "UPDATE opportunities SET company=?, role=?, url=?, location=?, "
            "salary_text=?, posted_date=?, dedupe_hash=?, company_id=?, "
            "work_mode=?, priority=?, score=? WHERE id=?",
            (merged["company"], merged["role"], merged["url"], merged["location"],
             merged["salary_text"], merged["posted_date"], new_hash, company_id,
             detect_work_mode(merged["location"], row["jd_text"]),
             "low" if pri == "dead" else pri,
             score_job(merged["role"], row["jd_text"], merged["posted_date"],
                       load_legacy_config()),
             job_id))
        conn.commit()
        return _fetch(conn, job_id)
    finally:
        conn.close()


def set_next_action(job_id: int, on: str | None, note: str = None) -> dict:
    """Follow-up reminder: `on` is YYYY-MM-DD; None clears date and note both."""
    if on is not None:
        try:
            date.fromisoformat(on)
        except ValueError:
            raise ValueError(f"invalid date {on!r} — use YYYY-MM-DD")
    conn = db.connect()
    try:
        _fetch(conn, job_id)
        clean_note = ((note or "").strip()[:200] or None) if on else None
        conn.execute("UPDATE opportunities SET next_action_date=?, "
                     "next_action_note=? WHERE id=?", (on, clean_note, job_id))
        conn.commit()
        return _fetch(conn, job_id)
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
