# career_hunt/jobposting.py
"""schema.org JobPosting extraction from arbitrary posting pages — the generic
half of paste-a-link. Most ATSes (Lever, Workday, SmartRecruiters) and many
company career sites embed a JSON-LD JobPosting block; parsing it yields exact
title/company/location/JD without per-vendor code. Stdlib only, zero network;
lives in career_hunt because it is shared domain parsing (sources never import
feeds/career_inbox)."""
import json
from html.parser import HTMLParser

from .htmltext import extract_text


class _PageMeta(HTMLParser):
    """Collects ld+json script bodies, <title> text, and og:title/og:site_name."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ld_blocks, self.meta, self.title_chunks = [], {}, []
        self._in_ld = self._in_title = False
        self._ld_chunks = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "script" and (a.get("type") or "").strip().lower() == "application/ld+json":
            self._in_ld, self._ld_chunks = True, []
        elif tag == "title":
            self._in_title = True
        elif tag == "meta":
            prop = a.get("property") or a.get("name") or ""
            if prop in ("og:title", "og:site_name") and (a.get("content") or "").strip():
                self.meta.setdefault(prop, a["content"].strip())

    def handle_endtag(self, tag):
        if tag == "script" and self._in_ld:
            self._in_ld = False
            self.ld_blocks.append("".join(self._ld_chunks))
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_ld:
            self._ld_chunks.append(data)
        elif self._in_title:
            self.title_chunks.append(data)


def _find_jobposting(value):
    if isinstance(value, dict):
        t = value.get("@type")
        types = t if isinstance(t, list) else [t]
        if any(isinstance(x, str) and x.strip().lower() == "jobposting" for x in types):
            return value
        graph = value.get("@graph")
        if isinstance(graph, list):
            return _find_jobposting(graph)
    elif isinstance(value, list):
        for v in value:
            hit = _find_jobposting(v)
            if hit is not None:
                return hit
    return None


def _str(v):
    return v.strip() if isinstance(v, str) and v.strip() else None


def _location(jp) -> str | None:
    loc = jp.get("jobLocation")
    if isinstance(loc, list):
        loc = loc[0] if loc else None
    if not isinstance(loc, dict):
        return None
    addr = loc.get("address")
    if isinstance(addr, str):
        return _str(addr)
    if isinstance(addr, dict):
        parts = [p for p in (_str(addr.get("addressLocality")),
                             _str(addr.get("addressRegion"))) if p]
        if parts:
            return ", ".join(parts)
    return _str(loc.get("name"))


def _num(n):
    if isinstance(n, bool):
        return None
    if isinstance(n, (int, float)):
        return str(int(n)) if float(n).is_integer() else str(n)
    return _str(n)


def _salary_text(base) -> str | None:
    if not isinstance(base, dict):
        return None
    currency = (base.get("currency") or "").strip().upper()
    value, unit = base.get("value"), None
    lo = hi = single = None
    if isinstance(value, dict):
        lo, hi = _num(value.get("minValue")), _num(value.get("maxValue"))
        single = _num(value.get("value"))
        unit = value.get("unitText")
    else:
        single = _num(value)
    amount = f"{lo} - {hi}" if lo and hi else (single or lo or hi)
    if not amount:
        return None
    per = {"HOUR": "per hour", "YEAR": "per year", "MONTH": "per month",
           "WEEK": "per week", "DAY": "per day"}.get((unit or "").strip().upper(), "")
    if currency in ("", "USD"):
        amount = " - ".join(f"${p}" for p in amount.split(" - "))
        return f"{amount} {per}".strip()
    return f"{amount} {currency} {per}".strip()


def jobposting_from_jsonld(html: str) -> dict | None:
    """First JobPosting node across all ld+json blocks, normalized to the Job
    field vocabulary; None when the page carries none. A broken block never
    kills the good one."""
    p = _PageMeta()
    p.feed(html or "")
    for block in p.ld_blocks:
        try:
            data = json.loads(block)
        except ValueError:
            continue
        jp = _find_jobposting(data)
        if jp is None:
            continue
        org = jp.get("hiringOrganization")
        if isinstance(org, dict):
            org = org.get("name")
        dp = jp.get("datePosted")
        et = jp.get("employmentType")
        if isinstance(et, list):
            et = et[0] if et else None
        desc = jp.get("description")
        return {
            "company": _str(org),
            "role": _str(jp.get("title")),
            "location": _location(jp),
            "jd_text": extract_text(desc) or None if isinstance(desc, str) else None,
            "posted_date": dp[:10] if isinstance(dp, str) and len(dp) >= 10 else None,
            "salary_text": _salary_text(jp.get("baseSalary")),
            "employment_type": _str(et),
        }
    return None


def page_hints(html: str) -> dict:
    """Fallback signals for pages without a JobPosting block."""
    p = _PageMeta()
    p.feed(html or "")
    title = p.meta.get("og:title") or _str(" ".join("".join(p.title_chunks).split()))
    return {"title": title or None, "site_name": p.meta.get("og:site_name")}
