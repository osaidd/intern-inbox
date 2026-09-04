# tests/test_jobposting.py
from career_hunt.jobposting import jobposting_from_jsonld, page_hints


def _page(*blocks, head=""):
    scripts = "\n".join(
        f'<script type="application/ld+json">{b}</script>' for b in blocks)
    return f"<html><head>{head}</head><body>{scripts}<p>filler</p></body></html>"


PLAIN = """{
  "@context": "https://schema.org/",
  "@type": "JobPosting",
  "title": "Software Engineering Intern",
  "hiringOrganization": {"@type": "Organization", "name": "Ramp"},
  "jobLocation": {"@type": "Place", "address": {"@type": "PostalAddress",
    "addressLocality": "New York", "addressRegion": "NY"}},
  "description": "<p>Build &amp; ship LLM product features.</p>",
  "datePosted": "2026-08-30T12:00:00Z",
  "employmentType": ["INTERN"],
  "baseSalary": {"@type": "MonetaryAmount", "currency": "USD",
    "value": {"@type": "QuantitativeValue", "minValue": 25, "maxValue": 35,
              "unitText": "HOUR"}}
}"""


def test_plain_jobposting():
    d = jobposting_from_jsonld(_page(PLAIN))
    assert d["company"] == "Ramp"
    assert d["role"] == "Software Engineering Intern"
    assert d["location"] == "New York, NY"
    assert d["jd_text"] == "Build & ship LLM product features."
    assert d["posted_date"] == "2026-08-30"
    assert d["employment_type"] == "INTERN"
    assert d["salary_text"] == "$25 - $35 per hour"


def test_graph_and_type_list_and_arrays():
    graph = ('{"@context":"https://schema.org","@graph":[{"@type":"WebSite","name":"x"},'
             '{"@type":["JobPosting","Thing"],"title":"Data Intern",'
             '"hiringOrganization":"Tessera"}]}')
    d = jobposting_from_jsonld(_page(graph))
    assert d["role"] == "Data Intern" and d["company"] == "Tessera"
    # top-level array block
    arr = '[{"@type":"BreadcrumbList"},{"@type":"JobPosting","title":"Ops Intern"}]'
    assert jobposting_from_jsonld(_page(arr))["role"] == "Ops Intern"
    # only the second of two blocks is a JobPosting
    d = jobposting_from_jsonld(_page('{"@type":"Organization","name":"n"}',
                                     '{"@type":"JobPosting","title":"PM Intern"}'))
    assert d["role"] == "PM Intern"


def test_broken_block_skipped_and_missing_fields_none():
    d = jobposting_from_jsonld(_page("{not json", '{"@type":"JobPosting","title":"X"}'))
    assert d["role"] == "X"
    assert d["company"] is None and d["location"] is None
    assert d["jd_text"] is None and d["posted_date"] is None
    assert d["salary_text"] is None and d["employment_type"] is None
    assert jobposting_from_jsonld(_page('{"@type":"Organization"}')) is None
    assert jobposting_from_jsonld("<html><body>no ld</body></html>") is None


def test_location_variants():
    lst = ('{"@type":"JobPosting","title":"T","jobLocation":[{"@type":"Place",'
           '"address":{"addressLocality":"Brooklyn","addressRegion":"NY"}},'
           '{"@type":"Place","address":{"addressLocality":"Austin"}}]}')
    assert jobposting_from_jsonld(_page(lst))["location"] == "Brooklyn, NY"
    txt = '{"@type":"JobPosting","title":"T","jobLocation":{"address":"Hoboken, NJ"}}'
    assert jobposting_from_jsonld(_page(txt))["location"] == "Hoboken, NJ"


def test_salary_variants():
    eur = ('{"@type":"JobPosting","title":"T","baseSalary":{"currency":"EUR",'
           '"value":{"minValue":25,"maxValue":35,"unitText":"YEAR"}}}')
    assert jobposting_from_jsonld(_page(eur))["salary_text"] == "25 - 35 EUR per year"
    single = ('{"@type":"JobPosting","title":"T","baseSalary":{"currency":"USD",'
              '"value":{"value":30,"unitText":"HOUR"}}}')
    assert jobposting_from_jsonld(_page(single))["salary_text"] == "$30 per hour"
    junk = '{"@type":"JobPosting","title":"T","baseSalary":"competitive"}'
    assert jobposting_from_jsonld(_page(junk))["salary_text"] is None


def test_page_hints():
    h = page_hints(_page(head='<title>Data Intern - Acme</title>'
                              '<meta property="og:title" content="Data Intern | Acme">'
                              '<meta property="og:site_name" content="Acme">'))
    assert h == {"title": "Data Intern | Acme", "site_name": "Acme"}
    h = page_hints(_page(head="<title>Data Intern - Acme</title>"))
    assert h == {"title": "Data Intern - Acme", "site_name": None}
    assert page_hints("<p>bare</p>") == {"title": None, "site_name": None}
