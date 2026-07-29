# career_hunt/models.py
"""Shared Job model — every source (feed, email parser, browser skill) returns this."""
import hashlib
from dataclasses import dataclass


def _norm(s):
    if not isinstance(s, str):
        return ""
    return " ".join(s.strip().lower().split())


def dedupe_hash(company, role, url) -> str:
    """SHA256 of company|role|url — byte-identical to the legacy jobspy_pull formula
    so historical dead rows keep suppressing re-ingestion. Do not change."""
    key = (f"{_norm(company)}|{_norm(role)}|"
           f"{(url.strip().lower().rstrip('/') if isinstance(url, str) else '')}")
    return hashlib.sha256(key.encode()).hexdigest()


@dataclass
class Job:
    company: str
    role: str
    url: str | None = None
    source: str = ""
    location: str | None = None
    office_address: str | None = None
    area: str | None = None
    work_mode: str = "unknown"  # onsite | hybrid | remote | unknown
    posted_date: str | None = None
    jd_text: str | None = None
    salary_text: str | None = None
    employment_type: str | None = None  # ATS type label (e.g. Ashby employmentType); not stored

    def dedupe_hash(self) -> str:
        return dedupe_hash(self.company, self.role, self.url)
