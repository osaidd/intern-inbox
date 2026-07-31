# career_hunt/score.py
"""Deterministic career-hunt scorer. Pure functions of (job, company, config) — zero
LLM, zero network. Scores are otherwise fixed at ingest; priority() is the one value
recomputed later, because company stage/headcount only arrives with enrichment."""
import re

from .config import Config
from .models import Job

# Stages strictly later than Series B — confirmed = auto-dead.
LATE_STAGES = ("series c", "series c+", "series d", "series e", "growth", "public", "acquired")

_INTERN_RE = re.compile(r"\bintern(?:ship)?s?\b|\bco-?op\b", re.IGNORECASE)
# JD signal must ASSERT the role is an internship — a bare mention is not enough
# (live 2026-07-29 false positives: benefits boilerplate "Interns are not
# eligible…", requirements lines "internship experience", "previous internships").
# The "this …" filler words exclude "not" so "this is not an internship" never hits.
_TOKEN = r"(?:intern(?:ship)?|co-?op)"
_JD_INTERN_RE = re.compile(
    rf"\bthis (?:(?!not\b)[\w-]+ ){{0,3}}{_TOKEN}\b"
    rf"|\b(?:is|as) an? (?:(?!not\b)[\w-]+ ){{0,3}}{_TOKEN}\b"
    rf"|\b{_TOKEN} (?:position|role|opportunity|placement)\b"
    rf"|\b(?:summer|fall|spring|winter) (?:\d{{4}} )?{_TOKEN}s?\b"
    rf"|\b\d+[- ](?:week|month) {_TOKEN}\b",
    re.IGNORECASE)


def is_internship(title, jd_text=None, employment_type=None) -> bool:
    """Internships-only red line, pipeline-wide:
    ANY explicit intern signal includes the row — intern/co-op in the title
    (word-boundary — 'Internal Tools' never matches), an 'Intern' employment
    type, or JD wording that asserts the role IS an internship. The intern
    signal SUPERSEDES a full-time/contract type label; a row is dropped only
    when no intern signal exists anywhere (e.g. a full-time/graduate role that
    is also labeled full-time)."""
    et = re.sub(r"[^a-z]", "", (employment_type or "").lower())
    if et in ("intern", "internship"):
        return True
    if _INTERN_RE.search(title or ""):
        return True
    return bool(_JD_INTERN_RE.search(jd_text or ""))


def is_nyc_metro(location) -> bool:
    if not isinstance(location, str):
        return False
    loc = location.lower()
    if "manhattan beach" in loc:   # CA beach town — 'manhattan' substring trap
        return False
    cfg_free_markers = ("new york", "nyc", "brooklyn", "manhattan", "queens", "bronx",
                        "staten island", "long island city",
                        "jersey city", "hoboken", "newark", "weehawken", "secaucus")
    return any(m in loc for m in cfg_free_markers)


def detect_work_mode(location, jd_text) -> str:
    blob = f"{location or ''} {(jd_text or '')[:2000]}".lower()
    if "hybrid" in blob:
        return "hybrid"
    if "remote" in (location or "").lower() or "fully remote" in blob:
        return "remote"
    if "on-site" in blob or "onsite" in blob or "in office" in blob or "in-office" in blob:
        return "onsite"
    return "unknown"


def passes_company_gates(company, jd_text, cfg: Config) -> bool:
    """Mega-corp blocklist + JD size red flags. Shared with callers that gate
    pasted JDs without a full Job/location context.
    Blocklist entries match on WORD BOUNDARIES, not raw substrings — 'EY' must
    not kill 'Grey State Apparel' (a real casualty). Name collisions on
    whole words ('Meta Viable Solutions') are accepted; enrichment is the truth."""
    comp = (company or "").lower()
    for b in cfg.exclude_companies:
        if re.search(rf"(?<![a-z0-9]){re.escape(b.lower())}(?![a-z0-9])", comp):
            return False
    text = (jd_text or "").lower()
    return not any(r.lower() in text for r in cfg.size_red_flags)


def matches(job: Job, cfg: Config) -> bool:
    """Ingest hard gates. False = never stored."""
    if cfg.interns_only and not is_internship(job.role, job.jd_text,
                                              job.employment_type):
        return False
    title = (job.role or "").lower()
    if any(k in title for k in cfg.exclude_keywords):
        return False
    if not passes_company_gates(job.company, job.jd_text, cfg):
        return False
    if not cfg.allow_remote and detect_work_mode(job.location, job.jd_text) == "remote":
        return False
    return is_nyc_metro(job.location)


def company_tier(stage, headcount, cfg: Config) -> str:
    st = (stage or "unknown").lower()
    if headcount is not None and headcount >= cfg.company.hard_cap_headcount:
        return "dead"
    if any(st.startswith(l) for l in LATE_STAGES):
        return "dead"
    if st in cfg.company.tier1_stages:
        if headcount is None or headcount <= cfg.company.tier1_max_headcount:
            return "tier1"
        return "dead"  # tier1 stage but >100 confirmed — hard cap already caught ≥100
    if st in cfg.company.tier2_stages:
        if headcount is None:
            return "unknown"  # Series B without size: not prime until size confirms ≤75
        return "tier2" if headcount <= cfg.company.tier2_max_headcount else "dead"
    return "unknown"


def location_tier(area_or_location, cfg: Config) -> int:
    loc = (area_or_location or "").lower()
    if any(m in loc for m in cfg.location_tier2):
        return 2
    return 1  # metro gate already passed; NYC proper (or unknown borough) = tier1


def role_strength(role, jd_text, cfg: Config) -> int:
    title = (role or "").lower()
    if any(t.lower() in title for t in cfg.target_titles):
        return 2
    text = f"{title}\n{(jd_text or '').lower()}"
    hits = sum(1 for k in cfg.profile_keywords if k in text)
    if hits >= 3:
        return 2
    return 1 if hits >= 1 else 0


def priority(job: Job, company, cfg: Config) -> str:
    """company: dict with 'stage'/'headcount' (a companies row), or None if unenriched."""
    ct = company_tier((company or {}).get("stage"), (company or {}).get("headcount"), cfg)
    if ct == "dead":
        return "dead"
    strength = role_strength(job.role, job.jd_text, cfg)
    if strength == 0:
        return "low"
    if ct == "unknown":
        # company not yet enriched: differentiate by role strength so day-one
        # inboxes aren't a flat wall of 'low' — 'high' stays reserved for
        # confirmed tier1 companies
        return "medium" if strength == 2 else "low"
    downgrades = ((ct == "tier2") + (location_tier(job.area or job.location, cfg) == 2)
                  + (strength == 1))
    return "high" if downgrades == 0 else "medium" if downgrades == 1 else "low"
