"""Parse LinkedIn job-alert emails (the ONLY sanctioned LinkedIn channel — never
scrape linkedin.com). Two card shapes observed in the wild (verified live
2026-07-11 against jobs-noreply@linkedin.com alerts):
  (a) the whole card is ONE anchor to /jobs/view/<id> whose inner text is
      ['Title', 'Company · Location', ...] — the current real format;
  (b) the anchor carries only the title and the 'Company · Location' line is
      the next text block after it — older/other templates.
The parser handles both; keep it anchored on those two invariants.

Precision over recall: a card is only emitted when a 'Company · Location'
separator line is found between its job anchor and the next one. Anchor text
with no such separator line is intentionally dropped rather than guessed at —
a bare text chunk (e.g. "Actively recruiting", "1 connection works here") is
not reliably a company name, and accepting it would pollute the pipeline with
garbage company rows. A missed card just recurs in the next alert email; a bad
row does not self-correct. `location` may still be `""`, but only in the
separator-present-with-empty-location case — never as a stand-in for a missing
separator."""
import re
from html.parser import HTMLParser

from ..models import Job

_ID = re.compile(r"/jobs/view/(\d+)")
_SEP = re.compile(r"\s*[··]\s*")


def normalize_linkedin_url(url) -> str | None:
    m = _ID.search(url or "")
    return f"https://www.linkedin.com/jobs/view/{m.group(1)}" if m else None


class _Extract(HTMLParser):
    """Collect (job_url, title) from anchors, and every text chunk in document
    order so each card's 'Company · Location' line can be paired with the
    anchor that precedes it."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.events = []            # ("link", url, []) | ("text", chunk)
        self._href = None

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href", "")
            self._href = normalize_linkedin_url(href)
            if self._href:
                self.events.append(["link", self._href, []])

    def handle_endtag(self, tag):
        if tag == "a":
            self._href = None

    def handle_data(self, data):
        text = " ".join(data.split())
        if not text:
            return
        if self._href and self.events and self.events[-1][0] == "link":
            self.events[-1][2].append(text)     # anchor text = title
        else:
            self.events.append(["text", text])


def parse_alert_html(html: str) -> list:
    """Return one card per /jobs/view/<id> anchor that has a following
    'Company · Location' separator line before the next anchor. Anchors
    without such a line (footer links, bare recruiter-status text with no
    separator, etc.) are dropped — see module docstring for why."""
    p = _Extract()
    p.feed(html)
    cards, seen = [], set()
    events = p.events
    for i, ev in enumerate(events):
        if ev[0] != "link":
            continue
        url, title_parts = ev[1], ev[2]
        if url in seen:
            continue
        inner = [t for t in title_parts if t.strip()]
        title = company = location = ""
        # shape (a): 'Company · Location' inside the anchor, after the title parts
        for j, chunk in enumerate(inner):
            parts = _SEP.split(chunk)
            if j > 0 and len(parts) >= 2:
                company, location = parts[0].strip(), parts[1].strip()
                title = " ".join(inner[:j]).strip()
                break
        # shape (b): anchor is title-only; company line follows before the next anchor
        if not company:
            title = " ".join(inner).strip()
            if not title:
                continue
            for later in events[i + 1:]:
                if later[0] == "link":
                    break
                parts = _SEP.split(later[1])
                if len(parts) >= 2:
                    company, location = parts[0].strip(), parts[1].strip()
                    break
        if not company or not title:
            continue                            # no separator line found — drop (precision over recall)
        seen.add(url)
        cards.append({"title": title, "company": company,
                      "location": location, "url": url})
    return cards


def to_jobs(cards: list) -> list:
    return [Job(company=c["company"], role=c["title"], url=c["url"],
                source="linkedin-mail", location=c["location"] or None)
            for c in cards]
