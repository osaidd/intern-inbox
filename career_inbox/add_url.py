# career_inbox/add_url.py
"""Paste-a-link intake: resolve any posting URL to a Job (board API -> JSON-LD ->
generic fallback), warn instead of silently dropping when a gate fails, store
through career_hunt.store.insert_job, and write the legacy fit score at ingest.

LinkedIn URLs are NEVER fetched (CLAUDE.md red line): the caller gets a
`linkedin_paste` outcome and re-POSTs with manual fields the user supplies.
The fetch happens BEFORE any write connection opens — never hold a write txn
across the network."""
import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

import db
from career_hunt import config as ch_config
from career_hunt.config import user_agent
from career_hunt.htmltext import extract_text
from career_hunt.jobposting import jobposting_from_jsonld, page_hints
from career_hunt.models import Job
from career_hunt.score import company_tier, gate_warnings
from career_hunt.sources import ats
from career_hunt.store import insert_job, normalize_company
from feeds.jd_hydrate import DEFAULT_UA, MIN_TEXT
from feeds.jobspy_pull import load_config as load_legacy_config
from feeds.jobspy_pull import score_job

MAX_BYTES = 2_000_000
LINKEDIN_MSG = ("LinkedIn blocks automated fetching — paste the job description "
                "text and I'll do the rest")
NO_POSTING_MSG = ("couldn't find a job posting on that page — paste the JD text "
                  "via /add-opportunity in Claude, or add it with the details filled in")


class BadUrl(ValueError):
    """User-facing guidance; the endpoint maps this to 422."""


class FetchFailed(Exception):
    """The pasted page could not be fetched; the endpoint maps this to 502."""


class _LinkedInRedirect(Exception):
    """A shortener/redirect landed on linkedin.com — the red line holds."""


def _is_linkedin(host: str) -> bool:
    host = (host or "").lower()
    return host in ("linkedin.com", "lnkd.in") or host.endswith(".linkedin.com")


def _board_ref(split) -> tuple[str, str] | None:
    """('ashby'|'greenhouse', slug) when the URL is a known board posting."""
    host = (split.hostname or "").lower()
    parts = [p for p in split.path.split("/") if p]
    if host == "jobs.ashbyhq.com" and parts:
        return ("ashby", parts[0])
    if host in ("job-boards.greenhouse.io", "boards.greenhouse.io") and parts:
        return ("greenhouse", parts[0])
    return None


def _fetch_html(url: str, _opener=None) -> str:
    """GET an arbitrary posting page with the neutral UA (the contact address is
    reserved for known board APIs — jd_hydrate.py:79 policy)."""
    opener = _opener or urllib.request.urlopen
    req = urllib.request.Request(url, headers=DEFAULT_UA)
    try:
        with opener(req, timeout=15) as resp:
            if "linkedin.com" in (getattr(resp, "geturl", lambda: "")() or ""):
                raise _LinkedInRedirect
            raw = resp.read(MAX_BYTES)
    except urllib.error.HTTPError as e:
        raise FetchFailed(f"HTTP {e.code}")
    except (urllib.error.URLError, OSError, TimeoutError):
        raise FetchFailed("network unreachable")
    return raw.decode("utf-8", errors="replace")


def _split_title(title) -> tuple[str | None, str | None]:
    """'Data Intern - Acme' -> ('Data Intern', 'Acme'); no separator -> (title, None)."""
    if not title:
        return None, None
    for sep in (" - ", " – ", " | "):
        if sep in title:
            left, right = title.split(sep, 1)
            return left.strip() or None, right.strip() or None
    return title.strip() or None, None


def _host_label(split) -> str:
    host = (split.hostname or "").removeprefix("www.")
    return host.split(".")[0].replace("-", " ").title()


def resolve(url: str, cfg, _opener=None) -> tuple[Job, str]:
    """(job, resolver) with resolver in ats|jsonld|fallback. Raises BadUrl /
    FetchFailed / _LinkedInRedirect. Applies NO gates — callers warn."""
    split = urllib.parse.urlsplit(url)
    ref = _board_ref(split)
    if ref:
        kind, slug = ref
        api = (ats.ASHBY_URL if kind == "ashby" else ats.GREENHOUSE_URL).format(org=slug)
        try:
            data = ats._get_json(api, _opener, user_agent(cfg))
            job = (ats.find_ashby if kind == "ashby"
                   else ats.find_greenhouse)(data, slug, url)
        except Exception:  # noqa: BLE001 — board API down; the page itself may still parse
            job = None
        if job:
            return job, "ats"
    html = _fetch_html(url, _opener)
    hints = page_hints(html)
    t_role, t_company = _split_title(hints["title"])
    d = jobposting_from_jsonld(html)
    if d:
        role = d["role"] or t_role
        company = d["company"] or hints["site_name"] or t_company or _host_label(split)
        if not role:
            raise BadUrl(NO_POSTING_MSG)
        return Job(company=company, role=role, url=url, location=d["location"],
                   jd_text=d["jd_text"], posted_date=d["posted_date"],
                   salary_text=d["salary_text"],
                   employment_type=d["employment_type"]), "jsonld"
    if not t_role:
        raise BadUrl(NO_POSTING_MSG)
    text = extract_text(html)
    return Job(company=hints["site_name"] or t_company or _host_label(split),
               role=t_role, url=url,
               jd_text=text if len(text) >= MIN_TEXT else None), "fallback"


def _enriched_dead_warning(job: Job, cfg) -> list:
    """A known over-cap company would land status='dead' and vanish from the
    default view — surface that before the write instead of after."""
    conn = db.connect_ro()
    try:
        row = conn.execute("SELECT stage, headcount FROM companies WHERE name_key=?",
                           (normalize_company(job.company),)).fetchone()
    finally:
        conn.close()
    if row and company_tier(row["stage"], row["headcount"], cfg) == "dead":
        size = f"{row['headcount']}p" if row["headcount"] is not None else "size unknown"
        return [f"{job.company} is enriched at {row['stage'] or 'unknown'}/{size} — "
                "over your size cap; will be stored as low priority"]
    return []


def add_from_url(url: str, force: bool = False, manual: dict | None = None,
                 _opener=None) -> dict:
    """The whole blocking flow behind POST /api/add-url. A URL is optional when
    `manual` fields are given — an offline opportunity (career fair, referral,
    a company with no posting) is a row like any other, minus the fetch."""
    started = datetime.now().isoformat(timespec="seconds")
    url = (url or "").strip()
    if not url and manual is None:
        raise BadUrl("paste a link — or fill in the details to add one by hand")
    split = urllib.parse.urlsplit(url) if url else None
    if url and (split.scheme not in ("http", "https") or not split.hostname):
        raise BadUrl("that doesn't look like a link — paste the posting's URL")
    cfg = ch_config.load()
    if manual is not None:
        m = manual if isinstance(manual, dict) else {}
        company = (m.get("company") or "").strip()
        role = (m.get("role") or "").strip()
        if not company or not role:
            raise BadUrl("company and role are required to add manually")
        job = Job(company=company, role=role, url=url or None, source="browser",
                  location=(m.get("location") or "").strip() or None,
                  jd_text=(m.get("jd_text") or "").strip() or None)
        resolver = "manual"
    elif _is_linkedin(split.hostname):
        return {"outcome": "linkedin_paste", "message": LINKEDIN_MSG}
    else:
        try:
            job, resolver = resolve(url, cfg, _opener)
        except _LinkedInRedirect:
            return {"outcome": "linkedin_paste", "message": LINKEDIN_MSG}
        job.source = "browser"
    if job.jd_text:
        job.jd_text = job.jd_text[:20000]
    warnings = gate_warnings(job, cfg) + _enriched_dead_warning(job, cfg)
    if warnings and not force:
        return {"outcome": "needs_confirm", "warnings": warnings,
                "parsed": {"company": job.company, "role": job.role,
                           "location": job.location, "salary_text": job.salary_text,
                           "posted_date": job.posted_date,
                           "jd_len": len(job.jd_text or "")}}
    legacy_cfg = load_legacy_config()
    conn = db.connect()
    try:
        outcome, _pri = insert_job(conn, job, cfg, override_gates=force)
        if outcome == "excluded":
            return {"outcome": "excluded",
                    "message": "the parsed row had no company/role — nothing stored"}
        h = job.dedupe_hash()
        s = score_job(job.role, job.jd_text, job.posted_date, legacy_cfg)
        if s is not None:
            conn.execute("UPDATE opportunities SET score=? WHERE dedupe_hash=? "
                         "AND score IS NULL", (s, h))
            conn.commit()
        row = conn.execute("SELECT id, company, role, priority FROM opportunities "
                           "WHERE dedupe_hash=?", (h,)).fetchone()
        db.log_run(skill="add-url", trigger="button", status="ok",
                   summary=f"{outcome}: {row['company']} — {row['role']}",
                   started_at=started,
                   finished_at=datetime.now().isoformat(timespec="seconds"),
                   metrics_json=json.dumps({"outcome": outcome, "forced": force,
                                            "resolver": resolver}))
        return {"outcome": outcome, "id": row["id"], "company": row["company"],
                "role": row["role"], "priority": row["priority"],
                "warnings": warnings}
    except Exception as e:
        db.log_run(skill="add-url", trigger="button", status="error",
                   summary=f"{type(e).__name__}: {e}"[:200], started_at=started,
                   finished_at=datetime.now().isoformat(timespec="seconds"),
                   metrics_json=json.dumps({"resolver": resolver, "forced": force}))
        raise
    finally:
        conn.close()
