import json
from pathlib import Path

from career_hunt import config as ch_config
from career_hunt.sources.github_intern import parse_listings

CFG = ch_config.load(ch_config.DEFAULT_PATH)
FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "github_listings.json").read_text())


def test_parse_filters_and_maps():
    jobs = parse_listings(FIXTURE, CFG)
    by_co = {j.company: j for j in jobs}
    assert "Solva" in by_co                      # NYC + relevant → kept
    assert "MegaCloud" not in by_co              # Seattle → dropped (location)
    assert "Tessera" not in by_co                # Remote → dropped
    assert "OldCo" not in by_co                  # inactive → dropped
    assert "Auctor" not in by_co                 # role_strength 0 → dropped (list noise gate)
    j = by_co["Solva"]
    assert j.source == "github" and j.url == "https://jobs.example.com/solva/1"
    assert j.posted_date == "2025-07-02" or j.posted_date.startswith("20")  # unix→ISO date
    assert j.location == "New York, NY"
