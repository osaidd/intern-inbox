"""career-inbox — standalone career app (spec 2026-07-12). Read-mostly FastAPI;
ALL writes route through career_inbox.actions (the narrow write surface)."""
import asyncio
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import db  # noqa: E402
from career_hunt import config as ch_config  # noqa: E402
from career_hunt.emailer import EmailError, render_digest, send  # noqa: E402
from career_hunt.families import role_family  # noqa: E402
from career_hunt.models import Job  # noqa: E402
from career_hunt.store import get_or_create_company, insert_job  # noqa: E402
from career_hunt.term import term  # noqa: E402
from career_inbox import actions, pull, wizard  # noqa: E402
from feeds.ats_pull import load_orgs  # noqa: E402
from feeds.envfile import load_env  # noqa: E402


def _checked_recently(minutes: int) -> bool:
    """True if a career-inbox-check started within the last `minutes` (auto-loop guard)."""
    conn = db.connect_ro()
    try:
        row = conn.execute(
            "SELECT started_at FROM run_log WHERE skill='career-inbox-check' "
            "ORDER BY started_at DESC, id DESC LIMIT 1").fetchone()
    finally:
        conn.close()
    if not row or not row["started_at"]:
        return False
    try:
        last = datetime.fromisoformat(row["started_at"])
    except ValueError:
        return False
    return datetime.now() - last < timedelta(minutes=minutes)


@asynccontextmanager
async def _lifespan(app: "FastAPI"):
    """In-process auto-check: every 30 min, skip if running or a check ran <25 min ago.
    Sleeps first, so a pytest-spawned app never fires a check during the test run."""
    async def loop():
        while True:
            await asyncio.sleep(30 * 60)
            try:
                if pull.STATE["running"] or _checked_recently(25):
                    continue
                await asyncio.to_thread(pull.full_check, "auto")
            except Exception:  # noqa: BLE001 — one bad check must not kill the loop
                pass
    task = asyncio.create_task(loop())
    try:
        yield
    finally:
        task.cancel()


app = FastAPI(title="career-inbox", lifespan=_lifespan)
# localhost-only app: reject DNS-rebinding (foreign Host headers). The port is
# not pinned so --port N keeps working.
from starlette.middleware.trustedhost import TrustedHostMiddleware  # noqa: E402
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])

LIVE = ("new", "shortlisted", "applied", "interviewing")
ALL_STATUSES = ("new", "shortlisted", "applied", "interviewing", "offer",
                "rejected", "dead")
PRIORITY_RANK = ("CASE o.priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 "
                 "WHEN 'low' THEN 2 ELSE 3 END")

JOB_COLS = ("o.id, o.company, o.role, o.url, o.location, o.priority, o.status, "
            "o.source, o.score, o.salary_text, o.work_mode, o.office_area, o.discovered_date, "
            "o.posted_date, o.last_seen, o.applied_date, o.notes, "
            "length(o.jd_text) AS jd_len, c.stage, c.headcount, c.sector, "
            "c.website, c.enrich_status, c.lat, c.lon")


def _statuses(param: str) -> tuple:
    if param == "live":
        return LIVE
    if param == "all":
        return ALL_STATUSES
    if param in ALL_STATUSES:
        return (param,)
    raise HTTPException(422, f"unknown statuses={param!r}")


def _rows(conn, sql, params=()):
    return [dict(r) for r in conn.execute(sql, params)]


@app.get("/api/jobs")
def jobs(statuses: str = "live"):
    want = _statuses(statuses)
    marks = ",".join("?" for _ in want)
    conn = db.connect_ro()
    try:
        rows = _rows(conn,
                     f"SELECT {JOB_COLS}, substr(o.jd_text, 1, 2000) AS jd_text "
                     "FROM opportunities o "
                     "LEFT JOIN companies c ON c.id = o.company_id "
                     f"WHERE o.status IN ({marks}) "
                     f"ORDER BY {PRIORITY_RANK}, o.score IS NULL, o.score DESC, "
                     "o.discovered_date DESC", want)
    finally:
        conn.close()
    for r in rows:
        r["family"] = role_family(r["role"])
        # jd_text is fetched only to derive the term — never shipped to the list
        r["term"] = term(r["role"], r.pop("jd_text"))
    return {"jobs": rows, "total": len(rows)}


@app.get("/api/jobs/{job_id}")
def job_detail(job_id: int):
    conn = db.connect_ro()
    try:
        rows = _rows(conn,
                     f"SELECT {JOB_COLS}, o.jd_text FROM opportunities o "
                     "LEFT JOIN companies c ON c.id = o.company_id WHERE o.id=?",
                     (job_id,))
    finally:
        conn.close()
    if not rows:
        raise HTTPException(404, "no such job")
    rows[0]["family"] = role_family(rows[0]["role"])
    rows[0]["term"] = term(rows[0]["role"], rows[0]["jd_text"])
    return rows[0]


@app.get("/api/meta")
def meta():
    conn = db.connect_ro()
    try:
        by_status = {r["status"]: r["n"] for r in _rows(
            conn, "SELECT status, count(*) n FROM opportunities GROUP BY status")}
        marks = ",".join("?" for _ in LIVE)
        by_pri = {r["priority"]: r["n"] for r in _rows(
            conn, f"SELECT priority, count(*) n FROM opportunities "
                  f"WHERE status IN ({marks}) GROUP BY priority", LIVE)}
        live_rows = _rows(conn, f"SELECT o.role, o.source, o.company, c.stage "
                                "FROM opportunities o "
                                "LEFT JOIN companies c ON c.id=o.company_id "
                                f"WHERE o.status IN ({marks})", LIVE)
        last = _rows(conn, "SELECT started_at, finished_at, status, summary FROM run_log "
                           "WHERE skill='career-inbox-check' "
                           "ORDER BY started_at DESC, id DESC LIMIT 1")
        sweep = _rows(conn, "SELECT started_at FROM run_log WHERE skill='ats-pull' "
                            "AND status='ok' ORDER BY started_at DESC, id DESC LIMIT 1")
    finally:
        conn.close()
    counts = {"live": sum(by_status.get(s, 0) for s in LIVE), **by_status,
              "high": by_pri.get("high", 0), "medium": by_pri.get("medium", 0),
              "low": by_pri.get("low", 0)}
    # the ATS page's "watching" ledger. A malformed sources.toml must degrade
    # the ledger, never 500 the whole dashboard.
    try:
        ashby_orgs, greenhouse_orgs = load_orgs()
        boards = len(ashby_orgs) + len(greenhouse_orgs)
    except Exception:  # noqa: BLE001
        boards = 0
    ats = {"boards": boards, "last_sweep": sweep[0] if sweep else None}
    return {"counts": counts,
            "families": sorted({role_family(r["role"]) for r in live_rows}),
            "stages": sorted({r["stage"] for r in live_rows if r["stage"]}),
            "sources": sorted({r["source"] for r in live_rows}),
            "ats": ats,
            "last_check": last[0] if last else None}


@app.get("/api/offices")
def offices():
    marks = ",".join("?" for _ in LIVE)
    conn = db.connect_ro()
    try:
        rows = _rows(conn,
                     "SELECT c.name AS company, c.lat, c.lon, c.stage, c.headcount, "
                     f"COUNT(o.id) AS roles, MIN({PRIORITY_RANK}) AS pri_rank "
                     "FROM companies c JOIN opportunities o ON o.company_id = c.id "
                     "WHERE c.lat IS NOT NULL AND c.lon IS NOT NULL "
                     f"AND o.status IN ({marks}) GROUP BY c.id", LIVE)
    finally:
        conn.close()
    back = {0: "high", 1: "medium", 2: "low", 3: "low"}
    return {"offices": [r | {"priority": back[r.pop("pri_rank")]} for r in rows]}


class StatusBody(BaseModel):
    status: str


class NoteBody(BaseModel):
    text: str = ""


class BulkBody(BaseModel):
    ids: list[int]
    action: str


@app.post("/api/jobs/{job_id}/status")
def post_status(job_id: int, body: StatusBody):
    try:
        return actions.set_status(job_id, body.status)
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.post("/api/jobs/{job_id}/note")
def post_note(job_id: int, body: NoteBody):
    try:
        return actions.set_note(job_id, body.text)
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.post("/api/jobs/bulk")
def post_bulk(body: BulkBody):
    try:
        return {"changed": actions.bulk(body.ids, body.action)}
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.post("/api/add")
def add_jobs(payload: list[dict]):
    """Ingestion door for external tooling: POST a list of postings and they land in
    the pipeline through the same gates and dedupe as any feed."""
    cfg = ch_config.load()
    stats = {"new": 0, "dup": 0, "excluded": 0}
    conn = db.connect()
    try:
        for item in payload:
            if item.get("stage_hint") or item.get("headcount_hint"):
                get_or_create_company(conn, item.get("company", ""), hints={
                    "stage": item.get("stage_hint"),
                    "headcount": item.get("headcount_hint"),
                    "enrich_source": "browser"})
            job = Job(company=item.get("company", ""), role=item.get("role", ""),
                      url=item.get("url"), source="browser",
                      location=item.get("location"), jd_text=item.get("jd_text"),
                      posted_date=item.get("posted_date"),
                      salary_text=item.get("salary_text"))
            outcome, _ = insert_job(conn, job, cfg)
            stats[outcome] += 1
    finally:
        conn.close()
    return stats


@app.post("/api/email-saved")
def email_saved(request: Request):
    _require_json(request)
    load_env()
    conn = db.connect_ro()
    try:
        rows = _rows(conn,
                     "SELECT company, role, url, priority, source FROM opportunities "
                     "WHERE status IN ('shortlisted','applied','interviewing') "
                     "ORDER BY CASE priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 "
                     "WHEN 'low' THEN 2 ELSE 3 END, score DESC")
    finally:
        conn.close()
    if not rows:
        raise HTTPException(409, "nothing shortlisted yet")
    cfg = ch_config.load()
    for r in rows:
        r.setdefault("source", "")
        r["priority"] = r["priority"] or "low"
    try:
        send(cfg.email, f"Intern Inbox: {len(rows)} in play", render_digest(rows))
    except EmailError as e:
        raise HTTPException(502, f"email failed: {e}")
    return {"sent": len(rows)}


def _require_json(request):
    """Cross-site form POSTs can reach bodyless endpoints without a CORS
    preflight; requiring a JSON content-type makes them same-origin-only."""
    ct = request.headers.get("content-type", "")
    if not ct.startswith("application/json"):
        raise HTTPException(415, "expected application/json")


@app.post("/api/pull")
async def api_pull(request: Request):
    _require_json(request)
    if pull.STATE["running"]:
        raise HTTPException(409, "check already running")
    pull.STATE["running"] = True     # set before the thread starts (double-POST race)
    asyncio.get_running_loop().run_in_executor(
        None, lambda: pull.full_check(trigger="button"))
    return {"started": datetime.now().isoformat(timespec="seconds")}


@app.get("/api/pull/status")
def pull_status():
    return pull.STATE


STATIC = Path(__file__).parent / "static"


@app.get("/api/wizard/state")
def wizard_state():
    s = wizard.state()
    s["presets"] = {k: {"label": v["label"]} for k, v in wizard.load_presets().items()}
    s["sizes"] = list(wizard.SIZE_PRESETS)
    return s


@app.post("/api/wizard/complete")
async def wizard_complete(request: Request):
    _require_json(request)
    try:
        # parsing lives inside the try so a truncated or non-object body is a
        # 422 like every other bad input, never an unhandled 500
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError("expected a JSON object")
        force = bool(body.pop("force", False))
        return wizard.apply(body, force=force)
    except wizard.WizardConflict as e:
        raise HTTPException(409, str(e))
    except (ValueError, TypeError, KeyError) as e:
        raise HTTPException(422, str(e))


@app.get("/")
def root():
    """Unconfigured installs land on the wizard, not a dashboard with no data."""
    from fastapi.responses import FileResponse, RedirectResponse
    if wizard.state()["configured"]:
        return FileResponse(STATIC / "index.html")
    return RedirectResponse("/welcome.html", status_code=302)


# The catch-all static mount MUST stay last — it swallows every unmatched path.
if STATIC.is_dir():
    from fastapi.staticfiles import StaticFiles
    app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
