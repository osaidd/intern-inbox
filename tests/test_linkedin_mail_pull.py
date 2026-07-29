from email.message import EmailMessage
from pathlib import Path

from career_hunt import config as ch_config
from feeds.linkedin_mail_pull import build_sources, fetch_alert_htmls

FIX = Path(__file__).parent / "fixtures"
HTML = (FIX / "linkedin_alert.html").read_text()
BUILTIN_HTML = (FIX / "builtin_alert.html").read_text()
WELLFOUND_HTML = (FIX / "wellfound_alert.html").read_text()


def _rfc822(html: str) -> bytes:
    msg = EmailMessage()
    msg["From"] = "LinkedIn Job Alerts <jobalerts-noreply@linkedin.com>"
    msg["Subject"] = "30+ new jobs for 'ai engineer intern'"
    msg.set_content("plain fallback")
    msg.add_alternative(html, subtype="html")
    return msg.as_bytes()


class FakeImap:
    def select(self, box):
        assert box == "INBOX"
        return ("OK", [b"1"])

    def search(self, charset, *criteria):
        assert any(b"jobalerts-noreply@linkedin.com" in c if isinstance(c, bytes)
                   else "jobalerts-noreply@linkedin.com" in c for c in criteria)
        return ("OK", [b"1 2"])

    def fetch(self, num, spec):
        return ("OK", [(b"1 (RFC822 {123}", _rfc822(HTML)), b")"])


class MultiSenderImap:
    """One mailbox, three senders — search() records which sender was asked for and
    fetch() answers with that sender's alert body (the real IMAP contract: search
    narrows by FROM, fetch just returns message ids)."""

    BODIES = {"jobs-noreply@linkedin.com": HTML,
              "support@builtin.com": BUILTIN_HTML,
              "team@hi.wellfound.com": WELLFOUND_HTML}

    def __init__(self):
        self.asked = []
        self._current = None

    def select(self, box):
        return ("OK", [b"3"])

    def search(self, charset, *criteria):
        crit = " ".join(str(c) for c in criteria)
        self._current = next((s for s in self.BODIES if s in crit), None)
        self.asked.append(self._current)
        return ("OK", [b"7"] if self._current else [b""])

    def fetch(self, num, spec):
        return ("OK", [(b"7 (RFC822 {1}", _rfc822(self.BODIES[self._current])), b")"])


def test_fetch_alert_htmls_extracts_html_parts():
    htmls = fetch_alert_htmls(FakeImap(), "jobalerts-noreply@linkedin.com", 14)
    assert len(htmls) == 2                    # two message ids, each yields the html part
    assert "AI Engineering Intern" in htmls[0]


def test_registry_lists_all_enabled_senders():
    cfg = ch_config.load()
    names = [n for n, *_ in build_sources(cfg)]
    assert names == ["linkedin", "builtin", "wellfound"]
    senders = {n: s for n, s, *_ in build_sources(cfg)}
    assert senders["builtin"] == "support@builtin.com"
    assert senders["wellfound"] == "team@hi.wellfound.com"


def test_registry_respects_disable_flag():
    cfg = ch_config.load()
    cfg.mail_sources.builtin.enabled = False
    assert [n for n, *_ in build_sources(cfg)] == ["linkedin", "wellfound"]


def test_each_sender_is_searched_and_parsed_with_its_own_parser():
    cfg = ch_config.load()
    imap = MultiSenderImap()
    parsed = {}
    for name, sender, parse, to_jobs in build_sources(cfg):
        htmls = fetch_alert_htmls(imap, sender, cfg.linkedin_lookback_days)
        parsed[name] = [j for h in htmls for j in to_jobs(parse(h))]
    assert imap.asked == ["jobs-noreply@linkedin.com", "support@builtin.com",
                          "team@hi.wellfound.com"]
    assert {j.source for j in parsed["linkedin"]} == {"linkedin-mail"}
    assert {j.source for j in parsed["builtin"]} == {"builtin-mail"}
    assert {j.source for j in parsed["wellfound"]} == {"wellfound-mail"}
    assert len(parsed["builtin"]) == 3 and len(parsed["wellfound"]) == 4


def test_wellfound_cards_carry_headcount_hints_for_the_feed():
    """The feed zips cards to jobs to reach headcount_hint — the pairing must hold."""
    cfg = ch_config.load()
    _, _, parse, to_jobs = next(s for s in build_sources(cfg) if s[0] == "wellfound")
    cards = parse(WELLFOUND_HTML)
    jobs = to_jobs(cards)
    assert len(cards) == len(jobs)
    pairs = {j.company: c["headcount_hint"] for c, j in zip(cards, jobs)}
    assert pairs["Nomad Data"] == 10 and pairs["Vantable"] == 1000
