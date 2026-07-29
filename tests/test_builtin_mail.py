from pathlib import Path

from career_hunt.sources.builtin_mail import (canonical_job_url, parse_alert_html,
                                              role_from_slug, to_jobs)

HTML = (Path(__file__).parent / "fixtures" / "builtin_alert.html").read_text()


def test_canonical_url_decodes_awstrack_redirect():
    href = ("https://cb4sdw3d.r.us-west-2.awstrack.me/L0/https:%2F%2Fbuiltin.com"
            "%2Fjob%2Fai-engineer%2F10408735%3Fi=abc%26utm_medium=email"
            "/1/01000198aa0f1c2d-3f4e5d6c/deadbeef=")
    assert canonical_job_url(href) == "https://builtin.com/job/ai-engineer/10408735"


def test_canonical_url_accepts_plain_and_rejects_non_job():
    assert canonical_job_url(
        "https://builtin.com/job/ai-engineer-intern/10399412?i=x"
    ) == "https://builtin.com/job/ai-engineer-intern/10399412"
    assert canonical_job_url(
        "https://cb4sdw3d.r.us-west-2.awstrack.me/L0/https:%2F%2Fbuiltin.com"
        "%2Fjobs%3Fsearch=ai/1/abc/def=") is None
    assert canonical_job_url("https://builtin.com/unsubscribe?u=123") is None
    assert canonical_job_url(None) is None


def test_role_from_slug():
    assert role_from_slug("ai-engineer") == "Ai Engineer"
    assert role_from_slug("ai-software-engineer") == "Ai Software Engineer"


def test_parse_cards():
    cards = parse_alert_html(HTML)
    assert len(cards) == 3                       # 4th anchor is the same job; chrome links dropped
    assert cards[0] == {
        "company": "PwC", "role": "AI Engineer",
        "location": "Hybrid Multiple Locations", "salary_text": "$50,500-$112,500",
        "url": "https://builtin.com/job/ai-engineer/10408735"}


def test_multi_word_company_with_suffix():
    """'Gaya Technologies Inc AI Software Engineer Remote United States' — the split
    point is the slug-derived role, not a guess about where the company ends."""
    card = parse_alert_html(HTML)[1]
    assert card["company"] == "Gaya Technologies Inc"
    assert card["role"] == "AI Software Engineer"
    assert card["location"] == "Remote United States"
    assert card["salary_text"] is None


def test_nyc_card():
    card = parse_alert_html(HTML)[2]
    assert (card["company"], card["role"]) == ("Solva", "AI Engineer Intern")
    assert card["location"] == "In Office New York, NY"


def test_duplicate_urls_collapse():
    assert len(parse_alert_html(HTML + HTML)) == 3


def test_fallback_when_role_text_is_punctuated():
    """Slug role absent verbatim (comma inside), so the fallback strips the full set
    of slug words back from the mode keyword."""
    html = """
    <a href="https://builtin.com/job/ai-engineer-intern/10500001?i=x">
      <span>Acme Labs</span><span>AI Engineer, Intern</span>
      <span>In Office</span><span>New York, NY</span></a>
    """
    card = parse_alert_html(html)[0]
    assert card["company"] == "Acme Labs"
    assert card["role"] == "Ai Engineer Intern"       # slug-derived, text was unusable
    assert card["location"] == "In Office New York, NY"


def test_ambiguous_card_skipped():
    """Anchor text uses a different role wording ('ML Engineer' vs the
    machine-learning-engineer slug) — company boundary is unknowable, so drop it."""
    html = """
    <a href="https://builtin.com/job/machine-learning-engineer/10500002?i=x">
      <span>Vantable ML Engineer</span><span>Remote</span><span>New York, NY</span></a>
    """
    assert parse_alert_html(html) == []


def test_card_without_mode_keyword_skipped():
    html = """
    <a href="https://builtin.com/job/data-scientist/10500003?i=x">
      <span>Some Company Data Analyst New York, NY</span></a>
    """
    assert parse_alert_html(html) == []


def test_to_jobs():
    cards = parse_alert_html(HTML)
    jobs = to_jobs(cards)
    assert len(jobs) == len(cards)               # 1:1 and in order — the feed zips them
    assert all(j.source == "builtin-mail" for j in jobs)
    assert jobs[0].url == "https://builtin.com/job/ai-engineer/10408735"
    assert jobs[0].salary_text == "$50,500-$112,500"
    assert jobs[2].location == "In Office New York, NY"
