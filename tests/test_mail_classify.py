# tests/test_mail_classify.py
from email.message import EmailMessage

import pytest

from career_hunt.mail_classify import (body_text, candidate_domains, classify,
                                       is_ats_host, is_blocked, is_bulk,
                                       registrable_domain)


@pytest.mark.parametrize("subject, body, verdict", [
    ("Thanks for applying to Ramp", "We received your application.", "application_received"),
    ("Your application was received", "", "application_received"),
    ("Osaid, your application was sent to Ramp", "", "application_received"),  # LinkedIn confirmation
    ("Next steps with Tessera", "Can you share your availability for a phone screen?", "interview"),
    ("Coding challenge", "Complete this HackerRank within 5 days", "interview"),
    ("Update on your application", "Unfortunately we will not be moving forward.", "rejection"),
    ("Thank you for interviewing", "We have decided to pursue other candidates.", "rejection"),
    ("Your offer letter", "Congratulations! Your offer details are attached.", "offer"),
    ("You have a new message", "Alex at Ramp sent you a message", "linkedin_message"),
    ("Quick question", "Saw your resume, do you have time Friday?", "interview"),  # 'time Friday'? no — 'schedule'? actually matched by nothing
])
def test_classify_table(subject, body, verdict):
    if subject == "Quick question":                    # human reply, no keyword
        assert classify(subject, body, is_ats=False, is_pipeline=True,
                        bulk=False) == "human_reply"
        return
    assert classify(subject, body, is_ats=True, is_pipeline=False,
                    bulk=False) == verdict


def test_classify_ordering_traps():
    # rejection wins over the interview word it contains
    assert classify("Thank you for interviewing",
                    "we will not be moving forward with your candidacy",
                    is_ats=True, is_pipeline=False, bulk=False) == "rejection"
    # marketing "offer" wording without offer-letter shape falls to interview
    assert classify("We offer great benefits!", "Interview scheduled for Monday",
                    is_ats=True, is_pipeline=False, bulk=False) == "interview"
    # "viewed your application" is NOT a confirmation
    assert classify("Your application was viewed", "The hiring team viewed your application",
                    is_ats=False, is_pipeline=False, bulk=False) == "other"


def test_classify_pipeline_and_bulk():
    assert classify("Re: intro", "Nice to meet you!", is_ats=False,
                    is_pipeline=True, bulk=False) == "human_reply"
    assert classify("Newsletter", "Product updates!", is_ats=False,
                    is_pipeline=True, bulk=True) == "other"
    assert classify("Anything", "Hello", is_ats=False,
                    is_pipeline=False, bulk=False) == "other"


def test_registrable_domain():
    assert registrable_domain("Jobs <no-reply@mail.Ramp.com>") == "ramp.com"
    assert registrable_domain("a@ramp.com") == "ramp.com"
    assert registrable_domain("mail.ramp.com") == "ramp.com"
    assert registrable_domain("https://www.Ramp.com/about") == "ramp.com"
    assert registrable_domain("careers.acme.co.uk") == "acme.co.uk"
    assert registrable_domain("not a domain") is None
    assert registrable_domain("localhost") is None
    assert registrable_domain("") is None
    assert registrable_domain(None) is None


def test_blocklists():
    assert is_blocked("greenhouse.io") and is_blocked("us.greenhouse.io")
    assert is_blocked("gmail.com") and is_blocked("linkedin.com")
    assert not is_blocked("ramp.com")
    assert is_ats_host("no-reply.ashbyhq.com") and not is_ats_host("ramp.com")


def test_candidate_domains():
    doms = candidate_domains("https://ramp.com",
                             ["https://jobs.ashbyhq.com/ramp/x",
                              "https://boards.greenhouse.io/ramp/jobs/1",
                              "https://www.linkedin.com/jobs/view/2",
                              "https://careers.tessera.dev/roles/3", None])
    assert doms == {"ramp.com", "tessera.dev"}
    assert candidate_domains(None, []) == set()


def test_is_bulk():
    assert is_bulk({"List-Unsubscribe": "<mailto:u@x.co>"})
    assert is_bulk({"Precedence": "bulk"})
    assert not is_bulk({"Subject": "hi"})
    assert not is_bulk(None)


def test_body_text_html_and_plain():
    m = EmailMessage()
    m["From"] = "a@x.co"
    m.set_content("plain body here")
    assert body_text(m) == "plain body here\n"
    h = EmailMessage()
    h["From"] = "a@x.co"
    h.add_alternative("<html><body><p>rich <b>body</b></p><script>x()</script></body></html>",
                      subtype="html")
    t = body_text(h)
    assert "rich" in t and "body" in t and "x()" not in t
