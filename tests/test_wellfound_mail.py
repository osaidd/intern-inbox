from pathlib import Path

from career_hunt.sources.wellfound_mail import parse_alert_html, to_jobs

HTML = (Path(__file__).parent / "fixtures" / "wellfound_alert.html").read_text()


def test_parse_cards():
    cards = parse_alert_html(HTML)
    assert len(cards) == 4
    assert cards[0] == {
        "company": "Leland", "role": "Startup Founders Coach",
        "location": "Remote only, United States", "salary_text": "$80–80k",
        "headcount_hint": 50, "url": None}


def test_headcount_upper_bound():
    cards = parse_alert_html(HTML)
    assert [c["headcount_hint"] for c in cards] == [50, 10, 1000, 200]


def test_boilerplate_chunks_skipped():
    """'Ready to Interview' / 'Actively Hiring' / 'Top N% ...' / 'Responds within ...'
    sit between the title and the company line — they must never become titles."""
    roles = [c["role"] for c in parse_alert_html(HTML)]
    assert roles == ["Startup Founders Coach", "AI Engineer",
                     "Founding GTM Engineer", "Product Operations Associate"]


def test_details_without_salary():
    """Location is not blindly 'the 2nd segment' — salary/exp/job-type segments are
    dropped first, so a card with no salary still yields the real location."""
    card = parse_alert_html(HTML)[2]
    assert card["salary_text"] is None
    assert card["location"] == "New York City"


def test_urls_are_none():
    """Wellfound links are opaque tracking hashes (StreetEasy precedent) — carrying
    them would defeat dedupe, so identity is company+role only."""
    assert all(c["url"] is None for c in parse_alert_html(HTML))


def test_company_line_without_title_is_dropped():
    html = "<p>Ready to Interview</p><p>Orphan Co / 11-50 Employees</p>"
    assert parse_alert_html(html) == []


def test_duplicate_cards_collapse():
    assert len(parse_alert_html(HTML + HTML)) == 4


def test_to_jobs():
    cards = parse_alert_html(HTML)
    jobs = to_jobs(cards)
    assert len(jobs) == len(cards)               # 1:1 and in order — the feed zips them
    assert all(j.source == "wellfound-mail" and j.url is None for j in jobs)
    assert jobs[1].company == "Nomad Data"
    assert jobs[1].location == "New York City"
    assert jobs[1].salary_text == "$120k–150k"
