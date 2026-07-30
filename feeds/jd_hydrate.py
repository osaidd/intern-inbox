"""Hydrate missing job descriptions: fetch the posting page for live rows that
have a url but no jd_text, extract readable text, then fill the legacy profile-fit
score and recompute the row's priority (fuller text can upgrade role strength).

Rules: NEVER fetches linkedin.com (their job-alert emails are the only LinkedIn
channel); polite sequential fetches (1.5s spacing, honest UA, 15s timeout); one
attempt per URL per RETRY_DAYS (jd_fetched_at stamp, migration 005); cap per run.

Run: uv run python -m feeds.jd_hydrate [--dry-run] [--cap N]
Writes: opportunities (jd_text/score/priority/jd_fetched_at via this feed +
recompute_priorities), run_log."""
import json
import sys
import time
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import db  # noqa: E402
from career_hunt import config as ch_config  # noqa: E402
from career_hunt.config import user_agent  # noqa: E402
from career_hunt.htmltext import extract_text  # noqa: E402, F401 — moved there; re-exported
from career_hunt.store import recompute_priorities  # noqa: E402
from feeds.jobspy_pull import load_config as load_legacy_config  # noqa: E402
from feeds.jobspy_pull import score_job  # noqa: E402

# Real runs send user_agent(cfg) — an honest UA carrying the contact address from
# YOUR config. This contact-less fallback only covers direct fetch_text() calls.
DEFAULT_UA = {"User-Agent": "intern-inbox (personal internship search)"}
CAP = 15
RETRY_DAYS = 7
MIN_TEXT = 400
SLEEP = 1.5


def fetch_text(url: str, _opener=None, ua: dict | None = None) -> str | None:
    """Fetch a posting page and return readable text, or None (best-effort)."""
    opener = _opener or urllib.request.urlopen
    req = urllib.request.Request(url, headers=ua or DEFAULT_UA)
    try:
        with opener(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001 — a dead posting page is normal, not fatal
        return None
    text = extract_text(html)
    return text if len(text) >= MIN_TEXT else None


def candidates(conn, cap: int):
    cutoff = (date.today() - timedelta(days=RETRY_DAYS)).isoformat()
    return conn.execute(
        "SELECT id, company, role, url, posted_date, company_id FROM opportunities "
        "WHERE status IN ('new','shortlisted','applied','interviewing') "
        "AND jd_text IS NULL AND url IS NOT NULL "
        "AND url NOT LIKE '%linkedin.com%' "
        "AND (jd_fetched_at IS NULL OR jd_fetched_at < ?) "
        "ORDER BY CASE priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 "
        "WHEN 'low' THEN 2 ELSE 3 END, score IS NULL, score DESC, id DESC LIMIT ?",
        (cutoff, cap)).fetchall()


def main(dry_run: bool = False, cap: int = CAP, trigger: str = "manual",
         _opener=None, _sleep=time.sleep):
    started = datetime.now().isoformat(timespec="seconds")
    legacy_cfg = load_legacy_config()
    cfg = ch_config.load()
    ua = user_agent(cfg)
    stats = {"tried": 0, "hydrated": 0, "thin_or_dead": 0, "rescored": 0}
    conn = db.connect()
    try:
        rows = candidates(conn, cap)
        touched_companies = set()
        for i, r in enumerate(rows):
            if i:
                _sleep(SLEEP)
            stats["tried"] += 1
            text = fetch_text(r["url"], _opener=_opener, ua=ua)
            if dry_run:
                continue
            today = date.today().isoformat()
            if text is None:
                conn.execute("UPDATE opportunities SET jd_fetched_at=? WHERE id=?",
                             (today, r["id"]))
                stats["thin_or_dead"] += 1
                continue
            s = score_job(r["role"], text, r["posted_date"], legacy_cfg)
            conn.execute(
                "UPDATE opportunities SET jd_text=?, jd_fetched_at=?, score=? WHERE id=?",
                (text[:20000], today, s, r["id"]))
            stats["hydrated"] += 1
            if s is not None:
                stats["rescored"] += 1
            if r["company_id"]:
                touched_companies.add(r["company_id"])
        conn.commit()
        for cid in touched_companies:   # fuller JD text can change role strength
            recompute_priorities(conn, cfg, cid)
    except Exception as e:
        if not dry_run:
            db.log_run(skill="jd-hydrate", trigger=trigger, status="error",
                       summary=f"{type(e).__name__}: {e}"[:200], started_at=started,
                       finished_at=datetime.now().isoformat(timespec="seconds"),
                       metrics_json=json.dumps(stats))
        raise
    finally:
        conn.close()
    summary = (f"tried={stats['tried']} hydrated={stats['hydrated']} "
               f"thin_or_dead={stats['thin_or_dead']} rescored={stats['rescored']}")
    if not dry_run:
        db.log_run(skill="jd-hydrate", trigger=trigger, status="ok", summary=summary,
                   started_at=started,
                   finished_at=datetime.now().isoformat(timespec="seconds"),
                   metrics_json=json.dumps(stats))
    print(summary)
    return stats


if __name__ == "__main__":
    cap = CAP
    if "--cap" in sys.argv:
        cap = int(sys.argv[sys.argv.index("--cap") + 1])
    main(dry_run="--dry-run" in sys.argv, cap=cap)
