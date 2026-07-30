"""Parse Wellfound "New jobs: X at Y and N more jobs" alert emails
(team@hi.wellfound.com). Verified against live alerts 2026-07-29.

Every link in these emails is an opaque tracking hash — the href carries no job
identity at all, and storing a per-recipient redirect is worse than storing no url,
because it makes every re-send look like a new row. So `url` is None and dedupe
rides on company+role, and the parser reads the TEXT stream instead of the anchors.

The text stream is a repeating triple:
    'Startup Founders Coach'                                  <- title
    'Leland / 11-50 Employees'                                <- company + headcount
    '$80–80k | Remote only, United States | 5 years of exp'   <- details (pipes)
with boilerplate badges ('Ready to Interview', 'Actively Hiring', 'Top 5% of
responders', 'Responds within three days') sprinkled between them.

The company line is the anchor of the whole parse: it is the one chunk with an
unmistakable shape. Title = the nearest non-boilerplate chunk above it (never
crossing into the previous card), details = the first piped chunk below it.
Cards with no title above them are dropped — precision over recall.
"""
import re

from html.parser import HTMLParser

from ..models import Job

_COMPANY = re.compile(r"^(?P<name>.+?)\s*/\s*(?P<lo>[\d,]+)(?:\s*-\s*(?P<hi>[\d,]+))?\+?"
                      r"\s+Employees$", re.IGNORECASE)
_BOILERPLATE = re.compile(
    r"^(ready to interview|actively hiring|top \d+% of responders?"
    r"|responds within .*|new jobs:.*|recruiting now|hiring now|view job|apply now"
    r"|you are receiving this .*|manage alerts|unsubscribe)$", re.IGNORECASE)
_NON_LOCATION = re.compile(r"\$|\d+\s*years? of exp|^(full|part)[ -]time$|^contract$"
                           r"|^internship$|^intern$|^freelance$|^co-?founder$",
                           re.IGNORECASE)


class _Text(HTMLParser):
    """Every visible text chunk, in document order."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.chunks = []

    def handle_data(self, data):
        text = " ".join(data.split())
        if text:
            self.chunks.append(text)


def _headcount(m) -> int | None:
    raw = m.group("hi") or m.group("lo")     # ranges: take the upper bound
    try:
        return int(raw.replace(",", ""))
    except (AttributeError, ValueError):
        return None


def _is_title(chunk: str) -> bool:
    return not (_BOILERPLATE.match(chunk) or "|" in chunk or _COMPANY.match(chunk))


def _details(chunk: str):
    """('$80–80k | Remote only, US | 5 years of exp') -> (location, salary_text).
    Segments that are plainly salary / experience / employment-type are dropped
    first, so a card with no salary still reports its real location."""
    parts = [p.strip() for p in chunk.split("|") if p.strip()]
    salary = next((p for p in parts if "$" in p), None)
    location = next((p for p in parts if not _NON_LOCATION.search(p)), None)
    return location, salary


def parse_alert_html(html: str) -> list:
    p = _Text()
    p.feed(html)
    chunks = p.chunks
    anchors = [i for i, c in enumerate(chunks) if _COMPANY.match(c)]
    cards, seen = [], set()
    for n, i in enumerate(anchors):
        m = _COMPANY.match(chunks[i])
        company = m.group("name").strip()
        floor = anchors[n - 1] + 1 if n else 0          # never steal the previous card's text
        title = next((chunks[j] for j in range(i - 1, floor - 1, -1)
                      if _is_title(chunks[j])), None)
        if not company or not title:
            continue
        ceil = anchors[n + 1] if n + 1 < len(anchors) else len(chunks)
        detail = next((chunks[j] for j in range(i + 1, ceil) if "|" in chunks[j]), None)
        location, salary = _details(detail) if detail else (None, None)
        key = (company.lower(), title.lower())
        if key in seen:
            continue
        seen.add(key)
        cards.append({"company": company, "role": title, "location": location,
                      "salary_text": salary, "headcount_hint": _headcount(m),
                      "url": None})
    return cards


def to_jobs(cards: list) -> list:
    """1:1 with `cards`, in order — feeds zip the two to reach `headcount_hint`,
    which belongs to the company row, not to the Job."""
    return [Job(company=c["company"], role=c["role"], url=None,
                source="wellfound-mail", location=c["location"] or None,
                salary_text=c["salary_text"])
            for c in cards]
