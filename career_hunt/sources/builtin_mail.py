"""Parse Built In "New AI Job Matches" alert emails (support@builtin.com).
Verified against live alerts 2026-07-29. Two invariants the parser is anchored on:

  (a) every job anchor is an SES click-tracking redirect —
      `https://<id>.r.us-west-2.awstrack.me/L0/<percent-encoded real url>/1/<hash>` —
      whose decoded payload is `https://builtin.com/job/<slug>/<id>?...`;
  (b) the anchor's inner text concatenates the card's fields with no separators:
      `PwC AI Engineer Hybrid Multiple Locations $50,500-$112,500`.

Because (b) has no delimiter, the ONLY reliable split point is the role — and the
role is knowable independently, from the URL slug. So: derive the role from the
slug, find it case-insensitively in the anchor text, and everything before it is
the company, everything after is the location/mode/salary blob.

Precision over recall (linkedin_mail.py precedent): when the slug role is not
recoverable from the anchor text the card is dropped rather than guessed at — a
wrong company name pollutes the companies table permanently, a missed card just
recurs in tomorrow's alert.
"""
import re
from html.parser import HTMLParser
from urllib.parse import unquote

from ..models import Job

_JOB = re.compile(r"https://builtin\.com/job/([a-z0-9][a-z0-9._-]*)/(\d+)", re.IGNORECASE)
_MODE = re.compile(r"(?<![a-z])(hybrid|remote|in office|in-office|on ?site)(?![a-z])",
                   re.IGNORECASE)
_SALARY = re.compile(r"\$[\d,]+")
_WORD = re.compile(r"[a-z0-9]+")


def canonical_job_url(href) -> str | None:
    """Decode a Built In job link to `https://builtin.com/job/<slug>/<id>` (query
    stripped so the same job in two emails dedupes). Non-job links -> None."""
    if not isinstance(href, str) or not href:
        return None
    raw = href.split("/L0/", 1)[1] if "/L0/" in href else href
    m = _JOB.search(unquote(raw))
    return f"https://builtin.com/job/{m.group(1).lower()}/{m.group(2)}" if m else None


def role_from_slug(slug: str) -> str:
    return " ".join(w.capitalize() for w in slug.replace("_", "-").split("-") if w)


class _Anchors(HTMLParser):
    """Collect (canonical_url, anchor_text) for every builtin.com/job/ anchor."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.anchors = []           # [url, [text chunks]]
        self._open = False

    def handle_starttag(self, tag, attrs):
        if tag != "a":
            return
        url = canonical_job_url(dict(attrs).get("href", ""))
        self._open = bool(url)
        if url:
            self.anchors.append([url, []])

    def handle_endtag(self, tag):
        if tag == "a":
            self._open = False

    def handle_data(self, data):
        text = " ".join(data.split())
        if text and self._open and self.anchors:
            self.anchors[-1][1].append(text)


def _split_on_role(text: str, slug_role: str):
    """Exact path: the slug-derived role appears verbatim (any case) in the anchor
    text. Returns (company, role_as_written, rest) or None."""
    m = re.search(re.escape(slug_role), text, re.IGNORECASE)
    if not m:
        return None
    return text[:m.start()].strip(" ,·-"), text[m.start():m.end()], text[m.end():].strip()


def _split_fallback(text: str, slug_role: str):
    """Fallback: the role is worded differently ('AI Engineer, Intern'), so cut at the
    first work-mode keyword and peel role words off the tail of the head. Only accept
    when EVERY slug word is consumed — a partial peel ('Vantable ML' left over from an
    'ML Engineer' card) means the company boundary is unknown, so drop the card."""
    m = _MODE.search(text)
    if not m:
        return None
    head, rest = text[:m.start()].strip(), text[m.start():].strip()
    want = {w for w in _WORD.findall(slug_role.lower())}
    tokens, consumed = head.split(), set()
    while tokens:
        tail = "".join(_WORD.findall(tokens[-1].lower()))
        if tail not in want:
            break
        consumed.add(tail)
        tokens.pop()
    company = " ".join(tokens).strip(" ,·-")
    if consumed != want or not company:
        return None
    return company, slug_role, rest


def parse_alert_html(html: str) -> list:
    """One card per distinct builtin.com job URL whose company/role split is certain."""
    p = _Anchors()
    p.feed(html)
    cards, seen = [], set()
    for url, chunks in p.anchors:
        if url in seen:
            continue
        text = " ".join(chunks).strip()
        slug_role = role_from_slug(_JOB.search(url).group(1))
        split = _split_on_role(text, slug_role) or _split_fallback(text, slug_role)
        if not split:
            continue
        company, role, rest = split
        if not company or not role:
            continue
        sal = _SALARY.search(rest)
        location = (rest[:sal.start()] if sal else rest).strip(" ,·-|")
        seen.add(url)
        cards.append({"company": company, "role": role, "location": location,
                      "salary_text": rest[sal.start():].strip() if sal else None,
                      "url": url})
    return cards


def to_jobs(cards: list) -> list:
    """1:1 with `cards`, in order — feeds zip the two to reach card-only fields."""
    return [Job(company=c["company"], role=c["role"], url=c["url"],
                source="builtin-mail", location=c["location"] or None,
                salary_text=c["salary_text"])
            for c in cards]
