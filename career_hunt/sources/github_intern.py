"""SimplifyJobs-format internship lists — structured listings.json over raw GitHub.
No scraping, no auth. A noisy source (thousands of rows), so this parser applies the
metro + role_strength>=1 pre-filters; store.insert_job re-checks all hard gates."""
import json
import urllib.request
from datetime import date

from ..config import Config, user_agent
from ..models import Job
from ..score import is_nyc_metro, role_strength


def _posted(entry) -> str | None:
    ts = entry.get("date_posted") or entry.get("date_updated")
    try:
        return date.fromtimestamp(int(ts)).isoformat()
    except (TypeError, ValueError, OSError):
        return None


def parse_listings(data: list, cfg: Config) -> list:
    jobs = []
    for e in data:
        if not e.get("active", False) or not e.get("is_visible", True):
            continue
        locations = e.get("locations") or []
        loc = next((l for l in locations if is_nyc_metro(l)), None)
        if loc is None:
            continue
        title, company = e.get("title") or "", e.get("company_name") or ""
        if role_strength(title, None, cfg) < 1:
            continue
        jobs.append(Job(company=company, role=title, url=e.get("url"),
                        source="github", location=loc, posted_date=_posted(e)))
    return jobs


def fetch(cfg: Config) -> list:
    ua = user_agent(cfg)
    jobs, errors = [], []
    for url in cfg.github_urls:
        try:
            req = urllib.request.Request(url, headers=ua)
            with urllib.request.urlopen(req, timeout=15) as resp:
                jobs += parse_listings(json.loads(resp.read().decode()), cfg)
        except Exception as e:  # noqa: BLE001 — one dead list never kills the pull
            errors.append(f"{url}: {e}")
    if errors and not jobs:
        raise RuntimeError("; ".join(errors))
    return jobs, errors
