"""career-inbox — standalone career app (spec 2026-07-12). Read-mostly FastAPI;
ALL writes route through career_inbox.actions (the narrow write surface)."""
import asyncio
import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import db  # noqa: E402
from career_hunt import config as ch_config  # noqa: E402
from career_hunt.emailer import EmailError, render_digest, send  # noqa: E402
from career_hunt.families import role_family  # noqa: E402
from career_hunt.models import Job  # noqa: E402
from career_hunt.store import get_or_create_company, insert_job  # noqa: E402
from career_hunt.term import term  # noqa: E402
from career_inbox import actions, add_url, pull, update, wizard  # noqa: E402
from feeds.ats_pull import load_orgs  # noqa: E402
from feeds.envfile import load_env  # noqa: E402


# Hosted-demo mode: the public instance at intern-inbox-demo.fly.dev runs the
# real app over invented seed data (automation/seed_demo.py) and is wiped hourly.
# Read once at import; the Dockerfile sets it, a normal install never does.
DEMO = os.environ.get("INTERN_INBOX_DEMO") == "1"
DEMO_BLOCKED = "This is the public demo — install your own inbox to use this."


def _demo_block():
    """Shut the endpoints that touch the owner's mail, config, or the network.
    Status/note/bulk stay open on purpose — triaging rows IS the demo, and the
    hourly reset undoes whatever visitors do."""
    if DEMO:
        raise HTTPException(403, DEMO_BLOCKED)


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
    Sleeps first, so a pytest-spawned app never fires a check during the test run.
    Never runs in demo mode: the public instance shows invented rows only, so it
    must not reach out to IMAP or the ATS APIs and mix real listings in."""
    if DEMO:
        yield
        return

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
# not pinned so --port N keeps working. The hosted demo is deliberately public
# and reached by its own hostname, where rebinding protection means nothing —
# so that one mode allows any Host.
from starlette.middleware.trustedhost import TrustedHostMiddleware  # noqa: E402
app.add_middleware(TrustedHostMiddleware,
                   allowed_hosts=["*"] if DEMO else ["127.0.0.1", "localhost"])

LIVE = ("new", "shortlisted", "applied", "interviewing")
ALL_STATUSES = ("new", "shortlisted", "applied", "interviewing", "offer",
                "rejected", "dead")
PRIORITY_RANK = ("CASE o.priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 "
                 "WHEN 'low' THEN 2 ELSE 3 END")

JOB_COLS = ("o.id, o.company_id, o.company, o.role, o.url, o.location, o.priority, o.status, "
            "o.source, o.score, o.salary_text, o.work_mode, o.office_area, o.discovered_date, "
            "o.posted_date, o.last_seen, o.applied_date, o.notes, "
            "o.next_action_date, o.next_action_note, "
            "length(o.jd_text) AS jd_len, c.stage, c.headcount, c.sector, "
            "c.website, c.enrich_status, c.lat, c.lon")

# Last-touch columns: correlated scalar subqueries, fine at personal-tracker
# scale; company-level contacts count for every row of that company.
CONTACT_COLS = (
    "(SELECT MAX(e.occurred_at) FROM contact_events e WHERE e.direction='out' "
    "AND (e.opportunity_id = o.id OR e.company_id = o.company_id)) AS last_out, "
    "(SELECT MAX(e.occurred_at) FROM contact_events e WHERE e.direction='in' "
    "AND (e.opportunity_id = o.id OR e.company_id = o.company_id)) AS last_in")


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
                     f"SELECT {JOB_COLS}, {CONTACT_COLS}, "
                     "substr(o.jd_text, 1, 2000) AS jd_text "
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
                     f"SELECT {JOB_COLS}, {CONTACT_COLS}, o.jd_text "
                     "FROM opportunities o "
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
        sug_open = conn.execute("SELECT COUNT(*) AS n FROM suggestions "
                                "WHERE status='open'").fetchone()["n"]
        due = _rows(conn, "SELECT id, company, role, next_action_date, "
                          "next_action_note FROM opportunities "
                          f"WHERE status IN ({marks}) AND next_action_date IS NOT NULL "
                          "AND next_action_date <= date('now', 'localtime') "
                          "ORDER BY next_action_date, id LIMIT 20", LIVE)
        mail_last = _rows(conn, "SELECT started_at, status, summary FROM run_log "
                                "WHERE skill='mail-scan' "
                                "ORDER BY started_at DESC, id DESC LIMIT 1")
    finally:
        conn.close()
    counts = {"live": sum(by_status.get(s, 0) for s in LIVE), **by_status,
              "high": by_pri.get("high", 0), "medium": by_pri.get("medium", 0),
              "low": by_pri.get("low", 0), "suggestions_open": sug_open}
    # the ATS page's "watching" ledger. A malformed sources.toml must degrade
    # the ledger, never 500 the whole dashboard.
    try:
        ashby_orgs, greenhouse_orgs = load_orgs()
        boards = len(ashby_orgs) + len(greenhouse_orgs)
    except Exception:  # noqa: BLE001
        boards = 0
    ats = {"boards": boards, "last_sweep": sweep[0] if sweep else None}
    # reply-scan state for the consent banner + transparency footer: consent is
    # the data/mail_scan_enabled marker, never implied by the alert-feed creds
    load_env()
    if not os.environ.get("CAREER_IMAP_PASS"):
        mail_state = "no-creds"
    else:
        mail_state = "on" if pull.MAIL_CONSENT.exists() else "off"
    out = {"counts": counts,
           "families": sorted({role_family(r["role"]) for r in live_rows}),
           "stages": sorted({r["stage"] for r in live_rows if r["stage"]}),
           "sources": sorted({r["source"] for r in live_rows}),
           "ats": ats,
           "mail_scan": {"state": mail_state,
                         "last": mail_last[0] if mail_last else None},
           "due": due,
           "last_check": last[0] if last else None}
    if DEMO:
        out["demo"] = True      # the front end's cue to raise the demo banner
    return out


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


# The caps are right for a normal install too, not just the demo: bulk acts on
# rows the user can actually see and a note is a line or two. Uncapped, `ids`
# reaches SQLite's 32,767-variable ceiling and the OperationalError surfaces as
# an unhandled 500, and `text` is a free memory sink on a 256MB box.
class NoteBody(BaseModel):
    text: str = Field("", max_length=10_000)


class BulkBody(BaseModel):
    ids: list[int] = Field(..., max_length=500)
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


# ---- suggestions / contacts / timeline (spec 2026-09-04) ----
# Accept/dismiss stay open in demo like status/note/bulk: triage IS the demo,
# and the demo DB carries no suggestions anyway.

@app.get("/api/suggestions")
def suggestions():
    conn = db.connect_ro()
    try:
        rows = _rows(conn,
                     "SELECT s.id, s.kind, s.opportunity_id, s.evidence, s.created_at, "
                     "o.company, o.role, o.status, m.from_addr, m.subject, m.sent_at "
                     "FROM suggestions s "
                     "JOIN opportunities o ON o.id = s.opportunity_id "
                     "LEFT JOIN email_messages m ON m.id = s.email_message_id "
                     "WHERE s.status='open' ORDER BY s.created_at DESC, s.id DESC")
    finally:
        conn.close()
    return {"suggestions": rows, "total": len(rows)}


def _suggestion_error(e: ValueError):
    return HTTPException(409 if "already" in str(e) else 404, str(e))


@app.post("/api/suggestions/{sug_id}/accept")
def post_accept_suggestion(sug_id: int, request: Request):
    _require_json(request)   # bodyless POST — the content-type gate IS the CSRF defense
    try:
        return actions.accept_suggestion(sug_id)
    except ValueError as e:
        raise _suggestion_error(e)


@app.post("/api/suggestions/{sug_id}/dismiss")
def post_dismiss_suggestion(sug_id: int, request: Request):
    _require_json(request)   # see accept — a forged form POST must never resolve a suggestion
    try:
        return actions.dismiss_suggestion(sug_id)
    except ValueError as e:
        raise _suggestion_error(e)


class EditBody(BaseModel):
    company: str | None = Field(None, max_length=200)
    role: str | None = Field(None, max_length=300)
    url: str | None = Field(None, max_length=2000)
    location: str | None = Field(None, max_length=200)
    salary_text: str | None = Field(None, max_length=200)
    posted_date: str | None = Field(None, max_length=32)


@app.post("/api/jobs/{job_id}/edit")
def post_edit(job_id: int, body: EditBody):
    """Field corrections; only keys actually sent are touched ('' clears)."""
    try:
        return actions.edit_job(job_id, body.model_dump(exclude_unset=True))
    except ValueError as e:
        raise HTTPException(404 if "no opportunity" in str(e) else 422, str(e))


class NextActionBody(BaseModel):
    date: str | None = Field(None, max_length=10)
    note: str = Field("", max_length=200)


@app.post("/api/jobs/{job_id}/next-action")
def post_next_action(job_id: int, body: NextActionBody):
    try:
        return actions.set_next_action(job_id, body.date or None, body.note)
    except ValueError as e:
        raise HTTPException(404 if "no opportunity" in str(e) else 422, str(e))


class ContactBody(BaseModel):
    direction: str
    occurred_at: str | None = Field(None, max_length=32)
    note: str = Field("", max_length=500)


@app.post("/api/jobs/{job_id}/contact")
def post_contact(job_id: int, body: ContactBody):
    try:
        return actions.log_contact(opportunity_id=job_id, direction=body.direction,
                                   occurred_at=body.occurred_at or None,
                                   note=body.note)
    except ValueError as e:
        raise HTTPException(404 if "no opportunity" in str(e) else 422, str(e))


class DomainBody(BaseModel):
    domain: str = Field(..., max_length=253)


@app.post("/api/companies/{company_id}/domain")
def post_company_domain(company_id: int, body: DomainBody):
    try:
        return actions.add_company_domain(company_id, body.domain)
    except ValueError as e:
        raise HTTPException(404 if "no company" in str(e) else 422, str(e))


@app.get("/api/jobs/{job_id}/timeline")
def timeline(job_id: int):
    """Merged stage + contact history for the detail panel, newest first.
    Contact events attach by row OR by the row's company (company-level touches
    count for every posting there)."""
    conn = db.connect_ro()
    try:
        job = conn.execute("SELECT id, company_id FROM opportunities WHERE id=?",
                           (job_id,)).fetchone()
        if job is None:
            raise HTTPException(404, "no such job")
        stages = _rows(conn,
                       "SELECT 'stage' AS kind, occurred_at, from_status, to_status, "
                       "source, note FROM stage_events WHERE opportunity_id=?",
                       (job_id,))
        contacts = _rows(conn,
                         "SELECT 'contact' AS kind, occurred_at, direction, channel, "
                         "subject, snippet, created_by FROM contact_events "
                         "WHERE opportunity_id=? "
                         "OR (company_id IS NOT NULL AND company_id=?)",
                         (job_id, job["company_id"]))
    finally:
        conn.close()
    events = sorted(stages + contacts, key=lambda e: e["occurred_at"] or "",
                    reverse=True)
    return {"events": events, "total": len(events)}


# ---- reply-scan consent (data/mail_scan_enabled marker) ----

@app.post("/api/mail-scan/enable")
async def mail_scan_enable(request: Request):
    _demo_block()
    _require_json(request)
    pull.MAIL_CONSENT.parent.mkdir(parents=True, exist_ok=True)
    pull.MAIL_CONSENT.write_text(datetime.now().isoformat(timespec="seconds"))
    return {"mail_scan": "on"}


@app.post("/api/mail-scan/disable")
async def mail_scan_disable(request: Request):
    _demo_block()
    _require_json(request)
    pull.MAIL_CONSENT.unlink(missing_ok=True)
    return {"mail_scan": "off"}


def _ingest(payload: list[dict]) -> dict:
    """The blocking half of /api/add. Kept sync and handed to a worker thread so
    the SQLite writes stay off the event loop, exactly as they did when this was
    a plain `def` handler and FastAPI ran it in its threadpool."""
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


@app.post("/api/add")
async def add_jobs(request: Request):
    """Ingestion door for external tooling: POST a list of postings and they land in
    the pipeline through the same gates and dedupe as any feed.

    The body is read by hand instead of declared as `payload: list[dict]`, because
    a typed signature makes FastAPI decode and validate the whole body BEFORE the
    handler runs — the demo's 403 would then arrive only after an attacker-sized
    JSON parse, on a 256MB box. Blocking first is what the other three closed
    endpoints already do; the isinstance check below keeps the 422 that the typed
    signature used to give for a body that is not a list of objects."""
    _demo_block()
    _require_json(request)
    try:
        payload = await request.json()
    except ValueError:
        raise HTTPException(422, "expected a JSON list of postings")
    if not isinstance(payload, list) or not all(isinstance(i, dict) for i in payload):
        raise HTTPException(422, "expected a JSON list of postings")
    return await asyncio.to_thread(_ingest, payload)


@app.post("/api/add-url")
async def add_url_endpoint(request: Request):
    """Paste-a-link: fetch the pasted posting URL, parse (board API -> JSON-LD ->
    fallback), warn on gate failures, store + score. Body read by hand for the
    same block-before-parse reason as /api/add; _demo_block is a security
    boundary here — the public demo must never fetch visitor-supplied URLs."""
    _demo_block()
    _require_json(request)
    try:
        body = await request.json()
    except ValueError:
        raise HTTPException(422, "expected a JSON object with a url")
    if not isinstance(body, dict) or not isinstance(body.get("url", ""), str):
        raise HTTPException(422, "expected a JSON object with a url")
    manual = body.get("manual")
    if manual is not None and not isinstance(manual, dict):
        raise HTTPException(422, "manual must be an object")
    try:
        result = await asyncio.to_thread(
            add_url.add_from_url, body.get("url", "")[:2000],
            bool(body.get("force")), manual)
    except add_url.BadUrl as e:
        raise HTTPException(422, str(e))
    except add_url.FetchFailed as e:
        raise HTTPException(502, f"couldn't fetch that page: {e}")
    if result.get("outcome") == "excluded":
        raise HTTPException(422, result.get("message", "nothing stored"))
    return result


@app.post("/api/email-saved")
def email_saved(request: Request):
    _demo_block()
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
    _demo_block()
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


@app.post("/api/update")
async def api_update(request: Request):
    """git pull --ff-only + uv sync. Blocked while a check runs (feeds mustn't
    have the code swapped under them); never runs migrations — next boot does."""
    _demo_block()
    _require_json(request)
    if pull.STATE["running"]:
        raise HTTPException(409, "a check is running — try again when it finishes")
    try:
        return await asyncio.to_thread(update.run_update)
    except update.UpdateBlocked as e:
        raise HTTPException(409, str(e))
    except update.UpdateFailed as e:
        raise HTTPException(502, str(e))


STATIC = Path(__file__).parent / "static"


@app.get("/api/wizard/state")
def wizard_state():
    s = wizard.state()
    s["presets"] = {k: {"label": v["label"]} for k, v in wizard.load_presets().items()}
    s["sizes"] = list(wizard.SIZE_PRESETS)
    s["prefill"] = wizard.prefill()
    return s


@app.post("/api/wizard/complete")
async def wizard_complete(request: Request):
    _demo_block()
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
    """Unconfigured installs land on the wizard, not a dashboard with no data.
    The demo never does: its container preconfigures itself, and a visitor who
    somehow arrives before that must still see the dashboard, not a wizard whose
    submit button is 403'd anyway."""
    from fastapi.responses import FileResponse, RedirectResponse
    if DEMO or wizard.state()["configured"]:
        return FileResponse(STATIC / "index.html")
    return RedirectResponse("/welcome.html", status_code=302)


# The catch-all static mount MUST stay last — it swallows every unmatched path.
if STATIC.is_dir():
    from fastapi.staticfiles import StaticFiles
    app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
