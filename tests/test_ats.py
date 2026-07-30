import io
import json
from pathlib import Path

from career_hunt import config as ch_config
from career_hunt.sources.ats import fetch, is_internship, parse_ashby, parse_greenhouse

CFG = ch_config.load(ch_config.DEFAULT_PATH)
FIX = Path(__file__).parent / "fixtures"
ASHBY = json.loads((FIX / "ashby_board.json").read_text())
GREENHOUSE = json.loads((FIX / "greenhouse_board.json").read_text())


def test_internship_red_line():
    """HARD RED LINE: every ATS listing
    must be an internship, and ANY explicit intern signal — title, JD text, or
    an 'Intern' employment type — includes the row, superseding a full-time/
    contract type label. Dropped only when NO intern signal exists anywhere."""
    assert is_internship("AI Engineering Intern")
    assert is_internship("Data Co-op")
    assert is_internship("Growth Co-Op (Fall 2026)")
    assert is_internship("Internship, Product")
    # intern word supersedes a non-intern type label — include it still
    assert is_internship("Software Engineering Intern", None, "FullTime")
    assert is_internship("Machine Learning Intern", None, "Full-Time")
    assert is_internship("Product Intern", None, "Contract")
    # 'Intern' employment type alone is enough — never hard-filtered out
    assert is_internship("Software Engineer", None, "Intern")
    # explicit "this role IS an internship" wording in the JD is enough
    assert is_internship("AI Engineer", "This is a 12-week summer internship.")
    assert is_internship("AI Resident", "Join us as an intern on the platform team.")
    assert is_internship("ML Engineer", "We are hiring for an internship position in NYC.")
    assert is_internship("Data Engineer", "Summer 2027 internship with the data team.")
    # JD boilerplate that merely MENTIONS interns is NOT an assertion (live 2026-07-29
    # false positives: TTD benefits note, requirements lines, negations)
    assert not is_internship("UX Designer II",
                             "Note: Interns are not eligible for variable incentive awards.")
    assert not is_internship("New Grad Software Engineer",
                             "Required - Internship, academic project, or equivalent experience.")
    assert not is_internship("Business Operations (Graduate)",
                             "You have 2-3 previous internships in high-growth startups.")
    assert not is_internship("Software Engineer", "This is not an internship.")
    # no intern signal anywhere → out
    assert not is_internship("AI Engineer")
    assert not is_internship("AI Engineer", "Own our LLM stack.", "FullTime")
    assert not is_internship("Graduate Software Engineer", None, "FullTime")
    assert not is_internship("Internal Tools Engineer")        # 'internal' must not match
    assert not is_internship(None)


def test_parse_ashby_filters_and_maps():
    jobs = parse_ashby(ASHBY, "solva", CFG)
    by_role = {j.role: j for j in jobs}
    assert "AI Engineering Intern" in by_role       # NYC primary + relevant → kept
    assert "Product Intern" in by_role              # NYC via secondaryLocations → kept
    assert "Data Co-op" in by_role                  # co-op title → kept
    assert "Software Engineering Intern" in by_role  # intern title beats FullTime label → kept
    assert "Software Engineer" in by_role           # 'Intern' employment type → kept
    assert "Machine Learning Engineer" not in by_role  # remote-only → dropped
    assert "AI Engineer" not in by_role             # isListed false → dropped
    assert "Office Manager" not in by_role          # no intern signal + role_strength 0 → dropped
    assert "AI Platform Engineer" not in by_role    # no intern signal anywhere → dropped (red line)
    j = by_role["AI Engineering Intern"]
    assert j.company == "Solva"                     # display name derived from org slug
    assert j.source == "ashby"
    assert j.url == "https://jobs.ashbyhq.com/solva/aaaa-1111"
    assert j.location == "New York, NY (HQ)"
    assert j.posted_date == "2026-07-20"            # publishedAt ISO → date
    assert "LLM and RAG product" in j.jd_text       # descriptionPlain carried whole
    assert j.salary_text == "$25 - $35 per hour"    # compensation → clean summary
    assert by_role["Product Intern"].salary_text is None  # absent stays None
    assert by_role["Product Intern"].location == "New York, NY"  # the NYC secondary wins


def test_parse_greenhouse_filters_and_maps():
    jobs = parse_greenhouse(GREENHOUSE, "tessera", CFG)
    by_role = {j.role: j for j in jobs}
    assert "Forward Deployed Engineer Intern" in by_role   # NYC + relevant → kept
    assert "AI Engineer" not in by_role     # id 200 London → dropped; id 350 NYC full-time → red line
    assert "Barista" not in by_role                        # non-intern → dropped
    j = by_role["Forward Deployed Engineer Intern"]
    assert j.company == "Tessera"                          # company_name field
    assert j.source == "greenhouse"
    assert j.url == "https://job-boards.greenhouse.io/tessera/jobs/100"
    assert j.posted_date == "2026-07-18"                   # first_published → date
    assert "LLM agents for fintech operations" in j.jd_text
    assert "&lt;" not in j.jd_text and "<p>" not in j.jd_text  # entities + tags stripped
    # no company_name on job 400 → slug-derived name; updated_at fallback date
    j4 = by_role["GTM Engineering Intern"]
    assert j4.company == "Tessera"
    assert j4.posted_date == "2026-07-25"


def _opener_for(bodies):
    """Fake urlopen: url → JSON body, or raises when body is an Exception."""
    def opener(req, timeout=None):
        url = req.full_url
        for frag, body in bodies.items():
            if frag in url:
                if isinstance(body, Exception):
                    raise body
                return io.BytesIO(json.dumps(body).encode())
        raise AssertionError(f"unexpected url {url}")
    return opener


def test_fetch_isolates_org_failures_and_paces():
    sleeps = []
    jobs, errors = fetch(["solva", "deadorg"], ["tessera"], CFG,
                         _opener=_opener_for({"job-board/solva": ASHBY,
                                              "job-board/deadorg": RuntimeError("HTTP 404"),
                                              "boards/tessera": GREENHOUSE}),
                         _sleep=sleeps.append)
    assert {j.source for j in jobs} == {"ashby", "greenhouse"}
    assert len(jobs) == 7                       # 5 ashby + 2 greenhouse survive the gates
    # red line holds across the fetch (employment_type travels on the Job)
    assert all(is_internship(j.role, j.jd_text, j.employment_type) for j in jobs)
    assert len(errors) == 1 and "deadorg" in errors[0]
    assert len(sleeps) == 2                     # pause between orgs, none before the first


def test_fetch_raises_only_on_total_failure():
    boom = _opener_for({"job-board/solva": RuntimeError("HTTP 404"),
                        "boards/tessera": RuntimeError("HTTP 500")})
    try:
        fetch(["solva"], ["tessera"], CFG, _opener=boom, _sleep=lambda s: None)
    except RuntimeError as e:
        assert "solva" in str(e) and "tessera" in str(e)
    else:
        raise AssertionError("expected RuntimeError when every org fails")
