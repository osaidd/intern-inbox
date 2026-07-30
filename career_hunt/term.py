# career_hunt/term.py
"""Internship term extraction — season (+ year) from the title, else a dated
season from the JD. Deterministic, no network. The title is the strong signal:
a bare season there counts ("Summer Intern"); in JD prose a season only counts
with a year attached ("Summer 2026 internship"), because "join us in the fall"
is noise. "Spring Boot"/"Spring Framework" never match."""
import re

_SEASON = r"(summer|fall|autumn|spring|winter)"
_TITLE_RE = re.compile(rf"\b{_SEASON}\b(?!\s+(?:boot|framework|mvc|cloud|batch|data|security))(?:\s*'?(\d{{4}}|\d{{2}})\b)?",
                       re.IGNORECASE)
_JD_RE = re.compile(rf"\b{_SEASON}\s*'?(\d{{4}})\b(?!\s*(?:boot|framework|mvc|cloud|batch|data|security))",
                    re.IGNORECASE)


def _label(season: str, year) -> str:
    season = season.capitalize()
    if season == "Autumn":
        season = "Fall"
    if not year:
        return season
    year = f"20{year}" if len(year) == 2 else year
    return f"{season} {year}"


def term(role, jd_text=None):
    hits = list(_TITLE_RE.finditer(role or ""))
    if hits:
        # prefer a dated mention ("… — Winter 2027 start") over a bare season
        m = next((h for h in hits if h.group(2)), hits[0])
        return _label(m.group(1), m.group(2))
    m = _JD_RE.search((jd_text or "")[:2000])
    if m:
        return _label(m.group(1), m.group(2))
    return None
