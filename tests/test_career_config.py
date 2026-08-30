from pathlib import Path

from career_hunt import config as ch_config


def test_load_falls_back_to_example(tmp_path, monkeypatch):
    # no config/career.toml in a fresh clone → example is used
    monkeypatch.setattr(ch_config, "USER_PATH", tmp_path / "career.toml")
    cfg = ch_config.load()
    assert cfg.interns_only is True          # product identity survives the template


def test_user_path_wins_when_present(tmp_path, monkeypatch):
    user = tmp_path / "career.toml"
    user.write_text(Path(ch_config.EXAMPLE_PATH).read_text()
                    .replace("allow_remote = false", "allow_remote = true"))
    monkeypatch.setattr(ch_config, "USER_PATH", user)
    assert ch_config.load().allow_remote is True


def test_user_agent_reads_contact():
    cfg = ch_config.load()
    cfg.email.to = "student@example.com"
    ua = ch_config.user_agent(cfg)
    assert ua["User-Agent"] == ("intern-inbox (personal internship search; "
                                "contact: student@example.com)")


def test_allow_late_stages_defaults_false():
    cfg = ch_config.load(ch_config.EXAMPLE_PATH)
    assert cfg.company.allow_late_stages is False
