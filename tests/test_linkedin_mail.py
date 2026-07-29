from pathlib import Path

from career_hunt.sources.linkedin_mail import (normalize_linkedin_url,
                                               parse_alert_html, to_jobs)

HTML = (Path(__file__).parent / "fixtures" / "linkedin_alert.html").read_text()


def test_normalize_url():
    assert normalize_linkedin_url(
        "https://www.linkedin.com/comm/jobs/view/4012345678/?trackingId=abc"
    ) == "https://www.linkedin.com/jobs/view/4012345678"
    assert normalize_linkedin_url("https://www.linkedin.com/comm/jobs/search/?k=ai") is None


def test_parse_cards():
    cards = parse_alert_html(HTML)
    assert len(cards) == 3
    first = cards[0]
    assert first["title"] == "AI Engineering Intern"
    assert first["company"] == "Solva"
    assert first["location"] == "New York, NY"
    assert first["url"] == "https://www.linkedin.com/jobs/view/4012345678"
    assert cards[1]["location"] == "Jersey City, NJ (Hybrid)"


def test_to_jobs():
    jobs = to_jobs(parse_alert_html(HTML))
    assert all(j.source == "linkedin-mail" for j in jobs)
    assert jobs[2].company == "Auctor"


def test_duplicate_ids_collapse():
    cards = parse_alert_html(HTML + HTML)   # same email twice
    assert len(cards) == 3


def test_no_separator_card_dropped():
    html = """
    <html><body>
    <table><tr><td>
      <a href="https://www.linkedin.com/comm/jobs/view/4022223333/?trk=email">
        <strong>Growth Associate</strong></a>
      <p>Actively recruiting</p>
    </td></tr></table>
    <table><tr><td>
      <a href="https://www.linkedin.com/comm/jobs/view/4033334444/?trk=email">
        <strong>Data Analyst</strong></a>
      <p>Vantable &#183; Brooklyn, NY</p>
    </td></tr></table>
    </body></html>
    """
    cards = parse_alert_html(html)
    assert len(cards) == 1
    assert cards[0]["url"] == "https://www.linkedin.com/jobs/view/4033334444"
    assert cards[0]["company"] == "Vantable"
    assert all(c["url"] != "https://www.linkedin.com/jobs/view/4022223333" for c in cards)


def test_real_shape_card_inside_anchor():
    """Live-verified 2026-07-11: real alerts put the whole card in ONE anchor —
    inner text is [title, 'Company · Location', ...]."""
    html = """
    <a href="https://www.linkedin.com/comm/jobs/view/4413361174/?trackingId=x">
      <table><tr><td><strong>HR, AI Automation Intern</strong></td></tr>
      <tr><td>Phamily &#183; New York, NY (On-site)</td></tr></table></a>
    <a href="https://www.linkedin.com/comm/jobs/view/4435408803/?trk=y">
      <span>AI Engineer Intern</span><span>Athena &#183; United States (Remote)</span></a>
    """
    cards = parse_alert_html(html)
    assert len(cards) == 2
    assert cards[0] == {"title": "HR, AI Automation Intern", "company": "Phamily",
                        "location": "New York, NY (On-site)",
                        "url": "https://www.linkedin.com/jobs/view/4413361174"}
    assert cards[1]["company"] == "Athena"
