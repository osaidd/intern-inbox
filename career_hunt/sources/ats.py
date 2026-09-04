"""Ashby + Greenhouse job-board APIs — free, keyless JSON with exact locations and
full JD text at ingest (discovered 2026-07-29 board scan: 176 new NYC rows in one
pass, far better than scraping). One GET per org board, sequential and paced; org
slugs come from config/sources.toml [ats] via feeds/ats_pull.py.
Board rows are noisy (every role at the org), so this parser applies the metro +
role_strength>=1 pre-filters like github_intern; store.insert_job re-checks all
hard gates.
HARD RED LINE: ATS rows are INTERNSHIPS ONLY — is_internship()
gates every row here (any intern signal in title/JD/type includes; the intern word
supersedes a full-time type label), and feeds/ats_pull.py re-checks before insert."""
import json
import re
import time
import urllib.request
from html import unescape

from ..config import Config, user_agent
from ..htmltext import extract_text
from ..models import Job
from ..score import is_nyc_metro, role_strength

ASHBY_URL = "https://api.ashbyhq.com/posting-api/job-board/{org}?includeCompensation=true"
GREENHOUSE_URL = "https://boards-api.greenhouse.io/v1/boards/{org}/jobs?content=true"
SLEEP = 1.0


# The internship red line is pipeline-wide and lives in
# career_hunt.score; re-exported here for the feed's re-check and test back-compat.
from ..score import _INTERN_RE, _JD_INTERN_RE, is_internship  # noqa: F401


def _org_name(org: str) -> str:
    """Display name from a board slug ('jane-street' -> 'Jane Street'). Casing is
    cosmetic: store.normalize_company lowercases, so slug-derived names dedupe
    against existing companies rows regardless."""
    return org.replace("-", " ").strip().title()


def _iso_date(ts) -> str | None:
    return ts[:10] if isinstance(ts, str) and len(ts) >= 10 else None


def parse_ashby(data: dict, org: str, cfg: Config) -> list:
    if "jobs" not in data:
        raise ValueError("no 'jobs' key — API shape changed?")
    jobs = []
    for e in data.get("jobs") or []:
        if not e.get("isListed", True):
            continue
        cands = ([e.get("location")]
                 + [s.get("location") for s in e.get("secondaryLocations") or []])
        loc = next((l for l in cands if is_nyc_metro(l)), None)
        if loc is None:
            continue
        title = (e.get("title") or "").strip()
        jd = e.get("descriptionPlain") or extract_text(e.get("descriptionHtml") or "")
        if not is_internship(title, jd, e.get("employmentType")):
            continue
        if role_strength(title, jd, cfg) < 1:
            continue
        comp = e.get("compensation") or {}
        salary = (comp.get("scrapeableCompensationSalarySummary")
                  or comp.get("compensationTierSummary"))
        jobs.append(Job(company=_org_name(org), role=title, url=e.get("jobUrl"),
                        source="ashby", location=loc,
                        posted_date=_iso_date(e.get("publishedAt")), jd_text=jd or None,
                        employment_type=e.get("employmentType"), salary_text=salary))
    return jobs


def parse_greenhouse(data: dict, org: str, cfg: Config) -> list:
    if "jobs" not in data:
        raise ValueError("no 'jobs' key — API shape changed?")
    jobs = []
    for e in data.get("jobs") or []:
        cands = ([(e.get("location") or {}).get("name")]
                 + [o.get("location") or o.get("name") for o in e.get("offices") or []])
        loc = next((l for l in cands if is_nyc_metro(l)), None)
        if loc is None:
            continue
        title = (e.get("title") or "").strip()
        jd = extract_text(unescape(e.get("content") or ""))  # content arrives entity-escaped
        if not is_internship(title, jd):   # board API carries no employment-type field
            continue
        if role_strength(title, jd, cfg) < 1:
            continue
        jobs.append(Job(company=e.get("company_name") or _org_name(org), role=title,
                        url=e.get("absolute_url"), source="greenhouse", location=loc,
                        posted_date=_iso_date(e.get("first_published")
                                              or e.get("updated_at")),
                        jd_text=jd or None))
    return jobs


def _norm_url(u: str) -> str:
    u = (u or "").strip().lower()
    u = u.split("#", 1)[0].split("?", 1)[0]
    return u.rstrip("/")


def find_ashby(data: dict, org: str, url: str) -> Job | None:
    """URL→posting lookup for a pasted Ashby URL. Applies NO gates — a paste is
    user intent, so remote/unlisted/non-intern entries are returned too; callers
    run gate_warnings. Matches the exact jobUrl or the posting-UUID path segment
    (covers /application suffixes and query junk). Caller stamps Job.source."""
    target = _norm_url(url)
    target_segs = set(target.split("/"))
    for e in data.get("jobs") or []:
        job_url = e.get("jobUrl") or ""
        if not job_url:
            continue
        if _norm_url(job_url) != target and \
           _norm_url(job_url).rsplit("/", 1)[-1] not in target_segs:
            continue
        cands = ([e.get("location")]
                 + [s.get("location") for s in e.get("secondaryLocations") or []])
        loc = next((l for l in cands if is_nyc_metro(l)), None) or e.get("location")
        jd = e.get("descriptionPlain") or extract_text(e.get("descriptionHtml") or "")
        comp = e.get("compensation") or {}
        salary = (comp.get("scrapeableCompensationSalarySummary")
                  or comp.get("compensationTierSummary"))
        return Job(company=_org_name(org), role=(e.get("title") or "").strip(),
                   url=job_url, location=loc,
                   posted_date=_iso_date(e.get("publishedAt")), jd_text=jd or None,
                   employment_type=e.get("employmentType"), salary_text=salary)
    return None


def find_greenhouse(data: dict, org: str, url: str) -> Job | None:
    """URL→posting lookup for a pasted Greenhouse URL. NO gates (see find_ashby).
    Matches the exact absolute_url or the numeric id in a /jobs/<id> path."""
    target = _norm_url(url)
    m = re.search(r"/jobs/(\d+)$", target)
    want_id = int(m.group(1)) if m else None
    for e in data.get("jobs") or []:
        if _norm_url(e.get("absolute_url") or "") != target and \
           (want_id is None or e.get("id") != want_id):
            continue
        cands = ([(e.get("location") or {}).get("name")]
                 + [o.get("location") or o.get("name") for o in e.get("offices") or []])
        loc = (next((l for l in cands if is_nyc_metro(l)), None)
               or (e.get("location") or {}).get("name"))
        jd = extract_text(unescape(e.get("content") or ""))
        return Job(company=e.get("company_name") or _org_name(org),
                   role=(e.get("title") or "").strip(), url=e.get("absolute_url"),
                   location=loc,
                   posted_date=_iso_date(e.get("first_published") or e.get("updated_at")),
                   jd_text=jd or None)
    return None


def _get_json(url: str, opener, ua: dict) -> dict:
    req = urllib.request.Request(url, headers=ua)
    with (opener or urllib.request.urlopen)(req, timeout=20) as resp:
        return json.loads(resp.read().decode())


def fetch(ashby_orgs: list, greenhouse_orgs: list, cfg: Config,
          _opener=None, _sleep=time.sleep):
    """All boards, sequentially, SLEEP apart. Returns (jobs, errors); raises only
    when every org failed (one dead board never kills the pull)."""
    boards = ([("ashby", o) for o in ashby_orgs]
              + [("greenhouse", o) for o in greenhouse_orgs])
    ua = user_agent(cfg)
    jobs, errors = [], []
    for i, (kind, org) in enumerate(boards):
        if i:
            _sleep(SLEEP)
        try:
            if kind == "ashby":
                jobs += parse_ashby(_get_json(ASHBY_URL.format(org=org), _opener, ua),
                                    org, cfg)
            else:
                jobs += parse_greenhouse(
                    _get_json(GREENHOUSE_URL.format(org=org), _opener, ua), org, cfg)
        except Exception as e:  # noqa: BLE001 — per-org isolation
            errors.append(f"{org}: {e}")
    if errors and not jobs:
        raise RuntimeError("; ".join(errors))
    return jobs, errors
