import pytest

from career_hunt import config as ch_config
from career_hunt.models import Job, dedupe_hash


def test_dedupe_hash_matches_legacy():
    """feeds.jobspy_pull must keep re-exporting the shared hash (back-compat import).
    Skips until the feeds package lands — career_hunt ships ahead of it."""
    jobspy_pull = pytest.importorskip("feeds.jobspy_pull")
    assert jobspy_pull.dedupe_hash is dedupe_hash


def test_dedupe_hash_golden():
    """Pinned digests — the live DB's dead rows depend on this exact formula
    (sha256 of 'company|role|url' normalized). If this test fails, dedupe against
    every existing row silently breaks. Do NOT update these constants; fix the code."""
    assert dedupe_hash("Solva", "AI Intern", "https://x.co/j/1/") == \
        "b9f816b28e4bea40a283832daab1dc75c362a3228158ea3ae37501552df20b3b"
    assert dedupe_hash(" Solva ", "ai  intern", None) == \
        "37db81ad17c70881e0d96252aa5fb002fedcbb653ed69fdaa420a6721a407e02"


def test_job_dataclass_hash():
    j = Job(company="Solva", role="AI Intern", url="https://x.co/j/1")
    assert j.dedupe_hash() == dedupe_hash("Solva", "AI Intern", "https://x.co/j/1")


def test_load_real_config():
    cfg = ch_config.load(ch_config.DEFAULT_PATH)
    assert cfg.allow_remote is False
    assert "seed" in cfg.company.tier1_stages
    assert cfg.company.tier2_max_headcount == 75
    assert cfg.company.hard_cap_headcount == 100
    assert any("jersey" in a.lower() for a in cfg.location_tier2)
    assert cfg.exclude_keywords and cfg.target_titles
    assert cfg.email.smtp_host == "smtp.gmail.com"
