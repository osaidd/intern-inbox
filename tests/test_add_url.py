# tests/test_add_url.py
"""Paste-a-link intake: URL validation, LinkedIn red line, the resolver chain
(board API -> JSON-LD -> fallback), gate warnings vs force, score-at-ingest."""
import json
import urllib.error
from pathlib import Path

import pytest

import db
from career_hunt import config as ch_config
from career_inbox import add_url
from feeds import jobspy_pull

FIX = Path(__file__).parent / "fixtures"
ASHBY = (FIX / "ashby_board.json").read_text()

_LD = """{{
  "@context": "https://schema.org/", "@type": "JobPosting",
  "title": "Software Engineering Intern",
  "hiringOrganization": {{"name": "Tessera"}},
  {location}
  "description": "<p>{jd}</p>",
  "datePosted": "2026-08-30",
  "employmentType": "INTERN"
}}"""
_JD = "Build LLM agents with RAG for product operations. " * 20

LD_NYC = ('<html><body><script type="application/ld+json">'
          + _LD.format(location='"jobLocation":{"address":{"addressLocality":"New York","addressRegion":"NY"}},', jd=_JD)
          + "</script></body></html>")
LD_SF = ('<html><body><script type="application/ld+json">'
         + _LD.format(location='"jobLocation":{"address":{"addressLocality":"San Francisco","addressRegion":"CA"}},', jd=_JD)
         + "</script></body></html>")
LD_NOLOC = ('<html><body><script type="application/ld+json">'
            + _LD.format(location="", jd=_JD) + "</script></body></html>")
FALLBACK = ("<html><head><title>Data Intern - Acme</title></head><body><p>"
            + _JD + "</p></body></html>")
THIN = "<html><head><title>Ops Intern - Tiny</title></head><body><p>short</p></body></html>"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "life.db")
    missing = tmp_path / "no-user-config.toml"
    monkeypatch.setattr(ch_config, "USER_PATH", missing)
    monkeypatch.setattr(jobspy_pull, "USER_PATH", missing)
    db.migrate()


def _opener(routes, calls=None):
    def open_(req, timeout=None):
        url = req.full_url
        if calls is not None:
            calls.append(url)
        for frag, body in routes.items():
            if frag in url:
                if isinstance(body, Exception):
                    raise body
                data = body.encode()

                class R:
                    def __enter__(self):
                        return self

                    def __exit__(self, *a):
                        return False

                    def read(self, n=-1):
                        return data

                    def geturl(self):
                        return url
                return R()
        raise AssertionError(f"unexpected url {url}")
    return open_


def _counts():
    conn = db.connect()
    try:
        opps = conn.execute("SELECT COUNT(*) FROM opportunities").fetchone()[0]
        runs = conn.execute("SELECT COUNT(*) FROM run_log").fetchone()[0]
        return opps, runs
    finally:
        conn.close()


def test_bad_urls_rejected(env):
    for bad in ("", "not a url", "javascript:alert(1)", "ftp://x.co/a"):
        with pytest.raises(add_url.BadUrl):
            add_url.add_from_url(bad)
    assert _counts() == (0, 0)


def test_linkedin_never_fetched(env):
    calls = []
    for u in ("https://www.linkedin.com/jobs/view/4242",
              "https://linkedin.com/jobs/view/4242", "https://lnkd.in/xyz"):
        out = add_url.add_from_url(u, _opener=_opener({}, calls))
        assert out["outcome"] == "linkedin_paste" and out["message"]
    assert calls == []          # the red line: zero network activity
    assert _counts() == (0, 0)  # no row, no run_log


def test_linkedin_manual_stores_like_any_paste(env):
    out = add_url.add_from_url(
        "https://www.linkedin.com/jobs/view/4242",
        manual={"company": "Ramp", "role": "Software Engineering Intern",
                "location": "New York, NY", "jd_text": _JD})
    assert out["outcome"] == "new"
    conn = db.connect()
    row = conn.execute("SELECT * FROM opportunities").fetchone()
    conn.close()
    assert row["source"] == "browser"
    assert row["url"] == "https://www.linkedin.com/jobs/view/4242"
    assert row["score"] is not None
    _, runs = _counts()
    assert runs == 1
    # manual without required fields is guidance, not a crash
    with pytest.raises(add_url.BadUrl):
        add_url.add_from_url("https://www.linkedin.com/jobs/view/1",
                             manual={"company": "", "role": "X"})


def test_ashby_url_resolves_via_board_api(env):
    out = add_url.add_from_url("https://jobs.ashbyhq.com/solva/aaaa-1111",
                               _opener=_opener({"api.ashbyhq.com": ASHBY}))
    assert out["outcome"] == "new" and out["warnings"] == []
    conn = db.connect()
    row = conn.execute("SELECT * FROM opportunities").fetchone()
    run = conn.execute("SELECT * FROM run_log").fetchone()
    conn.close()
    assert row["company"] == "Solva" and row["role"] == "AI Engineering Intern"
    assert row["source"] == "browser"       # stays on the Inbox tab
    assert row["location"] == "New York, NY (HQ)"
    assert row["salary_text"] == "$25 - $35 per hour"
    assert row["score"] is not None and row["status"] == "new"
    assert run["skill"] == "add-url" and run["trigger"] == "button"
    assert json.loads(run["metrics_json"])["resolver"] == "ats"


def test_dead_board_api_falls_through_to_page(env):
    routes = {"api.ashbyhq.com": urllib.error.HTTPError("u", 500, "boom", None, None),
              "jobs.ashbyhq.com": LD_NYC}
    out = add_url.add_from_url("https://jobs.ashbyhq.com/solva/aaaa-1111",
                               _opener=_opener(routes))
    assert out["outcome"] == "new"
    conn = db.connect()
    run = conn.execute("SELECT metrics_json FROM run_log").fetchone()
    conn.close()
    assert json.loads(run["metrics_json"])["resolver"] == "jsonld"


def test_jsonld_page_and_dup(env):
    op = _opener({"acme.dev": LD_NYC})
    out = add_url.add_from_url("https://acme.dev/careers/42", _opener=op)
    assert out["outcome"] == "new"
    conn = db.connect()
    row = conn.execute("SELECT * FROM opportunities").fetchone()
    conn.close()
    assert row["company"] == "Tessera" and row["role"] == "Software Engineering Intern"
    assert row["location"] == "New York, NY" and row["posted_date"] == "2026-08-30"
    assert "LLM agents" in row["jd_text"] and row["score"] is not None
    again = add_url.add_from_url("https://acme.dev/careers/42", _opener=op)
    assert again["outcome"] == "dup" and again["id"] == out["id"]
    assert _counts()[0] == 1


def test_gated_page_needs_confirm_then_force(env):
    op = _opener({"acme.dev": LD_SF})
    out = add_url.add_from_url("https://acme.dev/careers/9", _opener=op)
    assert out["outcome"] == "needs_confirm"
    assert out["warnings"] == ["'San Francisco, CA' is outside the NYC/NJ metro"]
    assert out["parsed"]["company"] == "Tessera" and out["parsed"]["jd_len"] > 0
    assert _counts() == (0, 0)              # no write, no run_log on refusal
    forced = add_url.add_from_url("https://acme.dev/careers/9", force=True, _opener=op)
    assert forced["outcome"] == "new" and forced["warnings"] == out["warnings"]
    conn = db.connect()
    row = conn.execute("SELECT status FROM opportunities").fetchone()
    conn.close()
    assert row["status"] == "new"           # forced adds are never auto-buried


def test_missing_location_warning_text(env):
    out = add_url.add_from_url("https://acme.dev/j/1", _opener=_opener({"acme.dev": LD_NOLOC}))
    assert out["outcome"] == "needs_confirm"
    assert "no location found on the page" in out["warnings"][0]


def test_fallback_title_split_and_thin_page(env):
    out = add_url.add_from_url("https://acme.dev/j/2", _opener=_opener({"acme.dev": FALLBACK}))
    assert out["outcome"] == "needs_confirm"        # no location on a bare page
    assert out["parsed"]["company"] == "Acme" and out["parsed"]["role"] == "Data Intern"
    forced = add_url.add_from_url("https://acme.dev/j/2", force=True,
                                  _opener=_opener({"acme.dev": FALLBACK}))
    assert forced["outcome"] == "new"
    conn = db.connect()
    row = conn.execute("SELECT jd_text FROM opportunities").fetchone()
    conn.close()
    assert row["jd_text"] and "LLM agents" in row["jd_text"]
    # thin page: role guessed, jd_text stays NULL (hydratable later)
    forced2 = add_url.add_from_url("https://tiny.dev/j", force=True,
                                   _opener=_opener({"tiny.dev": THIN}))
    assert forced2["outcome"] == "new"
    conn = db.connect()
    row = conn.execute("SELECT jd_text FROM opportunities WHERE company='Tiny'").fetchone()
    conn.close()
    assert row["jd_text"] is None


def test_unfetchable_page(env):
    with pytest.raises(add_url.FetchFailed):
        add_url.add_from_url("https://gone.dev/j",
                             _opener=_opener({"gone.dev": urllib.error.URLError("dns")}))
    assert _counts() == (0, 0)


def test_enriched_dead_company_warns_then_low(env):
    from career_hunt.store import get_or_create_company
    conn = db.connect()
    get_or_create_company(conn, "Tessera", hints={"stage": "series c", "headcount": 900,
                                                  "enrich_source": "test"})
    conn.close()
    op = _opener({"acme.dev": LD_NYC})
    out = add_url.add_from_url("https://acme.dev/careers/42", _opener=op)
    assert out["outcome"] == "needs_confirm"
    assert any("size cap" in w for w in out["warnings"])
    forced = add_url.add_from_url("https://acme.dev/careers/42", force=True, _opener=op)
    assert forced["outcome"] == "new" and forced["priority"] == "low"
    conn = db.connect()
    row = conn.execute("SELECT status, priority FROM opportunities").fetchone()
    conn.close()
    assert row["status"] == "new" and row["priority"] == "low"
