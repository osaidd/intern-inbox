# career_hunt/store.py
"""Insert path shared by every feed: gates → dedupe → company link → priority → row.
Feeds stay thin; nothing else writes opportunities/companies directly."""
import re
from datetime import date

import db

from .config import Config
from .models import Job
from .score import detect_work_mode, matches, priority

_SUFFIX = re.compile(r"[,.]?\s+(inc|llc|ltd|corp|co)\.?$", re.IGNORECASE)


def normalize_company(name: str) -> str:
    n = " ".join((name or "").strip().split())
    n = _SUFFIX.sub("", n)
    return n.strip(" ,.").lower()


def get_or_create_company(conn, name, hints=None) -> int:
    """Return the companies.id for `name`, creating the row if new.
    NOTE: on the create path this COMMITS the caller's connection — any pending
    writes on `conn` are committed along with the new company row."""
    key = normalize_company(name)
    row = conn.execute("SELECT id FROM companies WHERE name_key=?", (key,)).fetchone()
    if row:
        return row["id"] if hasattr(row, "keys") else row[0]
    h = hints or {}
    status = "ok" if h.get("stage") and h.get("headcount") is not None else "pending"
    # INSERT via the caller's conn (not db.insert, which opens a 2nd connection and
    # deadlocks when the caller holds an open write txn).
    cur = conn.execute(
        "INSERT INTO companies (name, name_key, stage, headcount, website, "
        "enrich_source, enrich_status) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (" ".join(name.strip().split()), key, h.get("stage"), h.get("headcount"),
         h.get("website"), h.get("enrich_source"), status))
    conn.commit()
    return cur.lastrowid


def insert_job(conn, job: Job, cfg: Config, dry_run: bool = False,
               override_gates: bool = False):
    """override_gates: a paste is user intent — skip matches() (the caller has
    already shown gate_warnings and the user said yes). Blank company/role and
    dedupe still apply; a dead-tier priority stores visible (new/low), never
    auto-buried."""
    if not (isinstance(job.company, str) and job.company.strip()
            and isinstance(job.role, str) and job.role.strip()):
        return ("excluded", None)
    if not override_gates and not matches(job, cfg):
        return ("excluded", None)
    h = job.dedupe_hash()
    row = conn.execute(
        "SELECT id, url, jd_text, location, posted_date, salary_text "
        "FROM opportunities WHERE dedupe_hash=?", (h,)).fetchone()
    if row:
        if not dry_run:
            _resight(conn, row, job)
        return ("dup", None)
    if dry_run:
        return ("new", "low")
    cid = get_or_create_company(conn, job.company)
    comp = dict(conn.execute("SELECT stage, headcount FROM companies WHERE id=?",
                             (cid,)).fetchone() or {})
    pri = priority(job, comp or None, cfg)
    status = "dead" if pri == "dead" and not override_gates else "new"
    stored_pri = "low" if pri == "dead" else pri
    db.insert("opportunities", {
        "source": job.source, "company": job.company.strip(), "role": job.role.strip(),
        "url": job.url, "location": job.location, "posted_date": job.posted_date,
        "jd_text": (job.jd_text or None) and job.jd_text[:20000],
        "salary_text": job.salary_text,
        "dedupe_hash": h, "priority": stored_pri, "company_id": cid,
        "work_mode": detect_work_mode(job.location, job.jd_text),
        "office_area": job.area, "status": status,
        # both dates from Python local time — the SQLite default is UTC and a
        # 9pm ET insert would otherwise be born with last_seen < discovered_date
        "discovered_date": date.today().isoformat(),
        "last_seen": date.today().isoformat(),
    })
    return ("new", stored_pri)


def _resight(conn, row, job: Job) -> None:
    """Re-sighting merge: bump last_seen; backfill ONLY missing facts.
    Never touches status/notes/priority/score (user triage is sacred)."""
    sets, vals = ["last_seen=?"], [date.today().isoformat()]
    for col, new in (("url", job.url), ("jd_text", (job.jd_text or None) and job.jd_text[:20000]),
                     ("location", job.location), ("posted_date", job.posted_date),
                     ("salary_text", job.salary_text)):
        if new and not row[col]:
            sets.append(f"{col}=?")
            vals.append(new)
    conn.execute(f"UPDATE opportunities SET {', '.join(sets)} WHERE id=?",
                 (*vals, row["id"]))
    conn.commit()


def recompute_priorities(conn, cfg: Config, company_id: int) -> int:
    comp = conn.execute("SELECT stage, headcount FROM companies WHERE id=?",
                        (company_id,)).fetchone()
    comp = dict(comp) if comp else None
    changed = 0
    rows = conn.execute(
        "SELECT id, company, role, url, location, jd_text, office_area "
        "FROM opportunities WHERE company_id=? AND status!='dead'", (company_id,)).fetchall()
    for r in rows:
        job = Job(company=r["company"], role=r["role"], url=r["url"],
                  location=r["location"], jd_text=r["jd_text"], area=r["office_area"])
        pri = priority(job, comp, cfg)
        if pri == "dead":
            conn.execute("UPDATE opportunities SET status='dead', priority='low' "
                         "WHERE id=?", (r["id"],))
        else:
            conn.execute("UPDATE opportunities SET priority=? WHERE id=?", (pri, r["id"]))
        changed += 1
    conn.commit()
    return changed
