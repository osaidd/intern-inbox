# tests/test_career_score.py
from career_hunt import config as ch_config
from career_hunt.models import Job
from career_hunt.score import (company_tier, detect_work_mode, is_nyc_metro,
                               location_tier, matches, priority, role_strength)

CFG = ch_config.load(ch_config.DEFAULT_PATH)


def _job(**kw):
    base = dict(company="Solva", role="AI Engineering Intern",
                url="https://x.co/1", location="New York, NY",
                jd_text="Build LLM agents with RAG for product ops.")
    base.update(kw)
    return Job(**base)


# ---- hard gates -------------------------------------------------------------
def test_remote_never_stored():
    assert matches(_job(location="Remote"), CFG) is False
    assert detect_work_mode("Remote", None) == "remote"
    assert detect_work_mode("New York, NY (Hybrid)", None) == "hybrid"


def test_outside_metro_never_stored():
    assert matches(_job(location="San Francisco, CA"), CFG) is False
    assert is_nyc_metro("Hoboken, NJ") is True
    assert is_nyc_metro(None) is False
    # substring traps: California beach towns are not the NYC metro (real
    # 2026-07-31 leak: K1 in "Manhattan Beach, CA" passed via 'manhattan')
    assert is_nyc_metro("Manhattan Beach, CA") is False
    assert matches(_job(location="Manhattan Beach, California"), CFG) is False
    assert is_nyc_metro("Manhattan, NY") is True


def test_exclude_title_and_megacorp():
    assert matches(_job(role="Senior AI Engineer"), CFG) is False
    assert matches(_job(company="Google"), CFG) is False


def test_size_red_flag_in_jd():
    assert matches(_job(jd_text="We are a Fortune 500 leader"), CFG) is False


def test_interns_only_gate_pipeline_wide():
    """The whole pipeline is internships — [hunt].interns_only
    gates every feed at ingest. Any explicit intern signal admits (title beats a
    full-time type label; 'Intern' type alone is enough); no signal → never stored."""
    assert CFG.interns_only is True                          # config default is ON
    assert matches(_job(role="AI Engineer",
                        jd_text="Own our LLM stack."), CFG) is False
    assert matches(_job(role="AI Engineering Intern"), CFG) is True
    assert matches(_job(role="Machine Learning Intern",
                        employment_type="FullTime"), CFG) is True   # intern word wins
    assert matches(_job(role="Software Engineer",
                        employment_type="Intern"), CFG) is True     # type alone admits
    assert matches(_job(role="AI Resident",
                        jd_text="This is a 12-week summer internship."), CFG) is True
    cfg_off = ch_config.load(ch_config.DEFAULT_PATH)
    cfg_off.interns_only = False
    assert matches(_job(role="AI Engineer", jd_text="Own our LLM stack."),
                   cfg_off) is True                          # flag off restores old gate


# ---- company tiers ----------------------------------------------------------
def test_company_tiers():
    assert company_tier("seed", 40, CFG) == "tier1"
    assert company_tier("series a", None, CFG) == "tier1"     # size unknown, stage prime
    assert company_tier("series b", 60, CFG) == "tier2"       # B allowed only ≤75
    assert company_tier("series b", 80, CFG) == "dead"        # B over 75 → dead
    assert company_tier("seed", 150, CFG) == "dead"           # hard cap ≥100
    assert company_tier("series c+", 50, CFG) == "dead"       # later than B → dead
    assert company_tier("public", 50, CFG) == "dead"
    assert company_tier(None, None, CFG) == "unknown"
    assert company_tier("unknown", None, CFG) == "unknown"


# ---- priority ---------------------------------------------------------------
T1 = {"stage": "seed", "headcount": 30}
T2B = {"stage": "series b", "headcount": 60}


def test_high_needs_all_three():
    assert priority(_job(), T1, CFG) == "high"


def test_one_downgrade_is_medium():
    assert priority(_job(location="Jersey City, NJ"), T1, CFG) == "medium"   # NJ office
    assert priority(_job(), T2B, CFG) == "medium"                            # Series B ≤75
    weak_role = _job(role="Marketing Intern", jd_text="Own our newsletter and gtm events.")
    assert priority(weak_role, T1, CFG) == "medium"                          # moderate role


def test_unknown_company_ranks_by_role_strength():
    """Unenriched companies: strong roles rank medium (day-one inboxes must not
    be a flat wall of 'low'); 'high' stays reserved for confirmed tier1."""
    assert priority(_job(), None, CFG) == "medium"          # target-title role
    assert priority(_job(), {"stage": None, "headcount": None}, CFG) == "medium"
    weak = _job(role="Ops Intern", jd_text="Keep the office running with data entry.")
    assert priority(weak, None, CFG) == "low"               # strength 1 stays low


def test_two_downgrades_low_and_dead_gate():
    assert priority(_job(role="Marketing Intern",
                         jd_text="Own our newsletter and gtm events.",
                         location="Jersey City, NJ"), T1, CFG) == "low"
    assert priority(_job(), {"stage": "seed", "headcount": 500}, CFG) == "dead"


def test_role_strength_levels():
    assert role_strength("AI Engineering Intern", "llm rag agents", CFG) == 2   # target title
    assert role_strength("Growth Intern", "own gtm outreach", CFG) == 1          # ≥1 keyword
    assert role_strength("Warehouse Associate", "lift boxes", CFG) == 0


def test_location_tiers():
    assert location_tier("Brooklyn, NY", CFG) == 1
    assert location_tier("Hoboken, NJ", CFG) == 2
    assert location_tier(None, CFG) == 1  # already metro-gated; unknown borough = benefit of doubt


def test_exclude_companies_word_boundary():
    """'EY' must not kill 'Grey State Apparel' (real 2026-07-13 false positive);
    whole-word collisions and real giants must still be excluded."""
    assert matches(_job(company="Grey State Apparel"), CFG) is True
    assert matches(_job(company="Honeycomb Systems"), CFG) is True   # 'EY' inside a word
    assert matches(_job(company="EY"), CFG) is False
    assert matches(_job(company="EY-Parthenon"), CFG) is False       # word-bounded by hyphen
    assert matches(_job(company="Palantir Technologies"), CFG) is False
    assert matches(_job(company="Jane Street Capital"), CFG) is False


# ---- gate_warnings ----------------------------------------------------------
def test_gate_warnings_empty_iff_matches():
    """gate_warnings is the single source of truth: [] exactly when matches() passes."""
    from career_hunt.score import gate_warnings
    cases = [_job(), _job(location="Remote"), _job(location="San Francisco, CA"),
             _job(location=None), _job(role="Senior AI Engineer"),
             _job(company="Google"), _job(jd_text="We are a Fortune 500 leader"),
             _job(role="AI Engineer", jd_text="Own our LLM stack."),
             _job(role="Software Engineer", employment_type="Intern")]
    for j in cases:
        assert (gate_warnings(j, CFG) == []) == matches(j, CFG), j


def test_gate_warning_messages():
    from career_hunt.score import gate_warnings
    assert gate_warnings(_job(), CFG) == []
    assert gate_warnings(_job(location=None), CFG) == \
        ["no location found on the page — can't confirm NYC/NJ"]
    assert gate_warnings(_job(location="San Francisco, CA"), CFG) == \
        ["'San Francisco, CA' is outside the NYC/NJ metro"]
    assert gate_warnings(_job(role="Senior AI Intern"), CFG) == \
        ["title matches exclude keyword 'senior'"]
    assert gate_warnings(_job(role="AI Engineer", jd_text="Own our LLM stack."), CFG) == \
        ["not an internship — this pipeline is internships only"]
    assert gate_warnings(_job(company="Google"), CFG) == \
        ["company is on your blocklist or the JD has size red flags"]
    # a remote row fails both the remote gate and the metro gate — both named
    w = gate_warnings(_job(location="Remote"), CFG)
    assert "remote role and allow_remote is off" in w
    assert any("outside the NYC/NJ metro" in m for m in w)


# ---- allow_late_stages config gate ------------------------------------------
def test_late_stage_dead_by_default():
    assert company_tier("series c", 40, CFG) == "dead"


def test_allow_late_stages_lets_late_companies_through():
    cfg = ch_config.load(ch_config.DEFAULT_PATH)
    cfg.company.allow_late_stages = True
    # late stage no longer auto-dead; falls through to tier lists -> unknown
    assert company_tier("series c", 40, cfg) == "unknown"
    # but the hard cap still applies regardless of stage
    cfg.company.hard_cap_headcount = 100
    assert company_tier("series c", 5000, cfg) == "dead"
