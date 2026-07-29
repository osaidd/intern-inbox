import feeds.config_load as cl


def test_communal_only(monkeypatch, tmp_path):
    monkeypatch.setattr(cl, "LOCAL", tmp_path / "none.toml")
    src = cl.load_sources()
    assert len(src["ats"]["ashby_orgs"]) >= 40      # seeded communal list present
    assert src["jobspy"]["location"] == "New York, NY"


def test_local_overlay_unions_lists_and_wins_scalars(monkeypatch, tmp_path):
    local = tmp_path / "sources.local.toml"
    local.write_text('[ats]\nashby_orgs = ["myboard", "ramp"]\n'
                     '[jobspy]\nresults_per_query = 5\n')
    monkeypatch.setattr(cl, "LOCAL", local)
    src = cl.load_sources()
    assert "myboard" in src["ats"]["ashby_orgs"]
    assert src["ats"]["ashby_orgs"].count("ramp") == 1     # union, not append-dupe
    assert src["jobspy"]["results_per_query"] == 5         # scalar: local wins
    assert src["jobspy"]["location"] == "New York, NY"     # untouched keys survive
