"""Check-now engine. Feeds run inline (each writes its own run_log row); jobspy is
budgeted to once/day; then a geocode batch fills company coords (enrichment cache —
the one sanctioned non-actions write, documented in CLAUDE.md)."""
import json
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import db  # noqa: E402
from career_hunt.geocode import geocode  # noqa: E402

STAMP = ROOT / "data" / "jobspy_last_pull"
ATS_STAMP = ROOT / "data" / "ats_last_pull"
MAIL_STAMP = ROOT / "data" / "mail_scan_last_pull"
# Consent marker for the reply/outreach scan: the feed runs ONLY while this file
# exists. Written/removed by the app's enable-disable endpoints and the wizard
# checkbox — never created implicitly.
MAIL_CONSENT = ROOT / "data" / "mail_scan_enabled"
GEO_BATCH = 10
STATE = {"running": False, "started": None, "steps": {}}

# run_log.trigger is a controlled vocabulary (manual/scheduled/button). full_check
# accepts a free-form trigger label (e.g. "auto", "test") for STATE/reporting; clamp
# it to a valid enum before it reaches the DB so the check-row write never fails.
_DB_TRIGGERS = {"manual", "scheduled", "button"}


def _db_trigger(trigger: str) -> str:
    if trigger in _DB_TRIGGERS:
        return trigger
    return "scheduled" if trigger == "auto" else "manual"


def _stamp_due(path: Path) -> bool:
    try:
        return path.read_text().strip() != date.today().isoformat()
    except FileNotFoundError:
        return True


def _stamp_write(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(date.today().isoformat())


def jobspy_due() -> bool:
    return _stamp_due(STAMP)


def write_stamp() -> None:
    _stamp_write(STAMP)


def _linkedin():
    import os
    from feeds.envfile import load_env
    load_env()
    if not os.environ.get("CAREER_IMAP_PASS"):
        return None, "not configured (no Gmail app password — see SETUP.md)"
    from feeds.linkedin_mail_pull import main
    return main(trigger="scheduled")  # feeds share run_log's trigger enum


def _github():
    from feeds.github_intern_pull import main
    return main(trigger="scheduled")


def _jobspy():
    if not jobspy_due():
        return None  # skipped
    try:
        from feeds.jobspy_pull import main
        main(trigger="scheduled")
        return {"ran": True}
    finally:
        write_stamp()  # even on failure: one attempt per day


def _ats_main():
    from feeds.ats_pull import main
    return main(trigger="scheduled")


def _ats():
    # Board JSON barely changes intra-day and each run hits every org — one
    # attempt per day, jobspy-style, even on failure.
    if not _stamp_due(ATS_STAMP):
        return None  # skipped
    try:
        return _ats_main()
    finally:
        _stamp_write(ATS_STAMP)


def _jd_hydrate():
    from feeds.jd_hydrate import main
    stats = main(cap=8, trigger="scheduled")
    # 'new' here = newly hydrated JDs (this connector adds text, not rows)
    return {"new": stats["hydrated"]}


def _mail_scan():
    if not MAIL_CONSENT.exists():
        return None, "off — enable reply tracking in the app"
    if not _stamp_due(MAIL_STAMP):
        return None  # skipped (daily budget)
    import os
    from feeds.envfile import load_env
    load_env()
    if not os.environ.get("CAREER_IMAP_PASS"):
        return None, "not configured (no Gmail app password — see SETUP.md)"
    try:
        from feeds.mail_scan import main
        return main(trigger="scheduled")  # 'new' = new suggestions
    finally:
        _stamp_write(MAIL_STAMP)  # even on failure: one attempt per day


def _geocode_batch():
    conn = db.connect()
    done = 0
    try:
        rows = conn.execute(
            "SELECT id, COALESCE(office_address, hq_address) AS addr FROM companies "
            "WHERE lat IS NULL AND COALESCE(office_address, hq_address) IS NOT NULL "
            "LIMIT ?", (GEO_BATCH,)).fetchall()
        for r in rows:
            hit = geocode(f"{r['addr']}, New York")
            if hit:
                conn.execute("UPDATE companies SET lat=?, lon=? WHERE id=?",
                             (hit[0], hit[1], r["id"]))
                conn.commit()   # per hit — never hold a write txn across a geocode call
                done += 1
    finally:
        conn.close()
    return {"geocoded": done, "candidates": len(rows)}


CONNECTORS = [("linkedin", _linkedin), ("github", _github), ("ats", _ats),
              ("jobspy", _jobspy), ("jd", _jd_hydrate), ("mail", _mail_scan)]


def full_check(trigger: str = "manual") -> dict:
    started = datetime.now().isoformat(timespec="seconds")
    STATE.update(running=True, started=started, steps={})
    ok = err = 0
    try:
        for name, fn in CONNECTORS:
            try:
                stats = fn()
                if isinstance(stats, tuple) and stats[0] is None:
                    STATE["steps"][name] = stats[1]      # e.g. mail not configured
                elif stats is None:
                    STATE["steps"][name] = "skipped (daily budget)"
                else:
                    STATE["steps"][name] = f"ok:{stats.get('new', '?')}new"
                    ok += 1
            except Exception as e:  # noqa: BLE001 — isolation: next connector runs
                STATE["steps"][name] = f"error: {type(e).__name__}: {e}"[:120]
                err += 1
        try:
            g = _geocode_batch()
            STATE["steps"]["geocode"] = str(g["geocoded"])
        except Exception as e:  # noqa: BLE001
            STATE["steps"]["geocode"] = f"error: {e}"[:120]
        summary = " ".join(f"{k}={v.split(':')[0] if ':' in v else v}"
                           for k, v in STATE["steps"].items())
        status = "ok" if err == 0 else "partial" if ok else "error"
        db.log_run(skill="career-inbox-check", trigger=_db_trigger(trigger), status=status,
                       summary=summary[:200], started_at=started,
                       finished_at=datetime.now().isoformat(timespec="seconds"),
                       metrics_json=json.dumps(STATE["steps"]))
        return {"status": status, "steps": dict(STATE["steps"])}
    finally:
        STATE["running"] = False
