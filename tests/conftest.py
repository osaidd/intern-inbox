"""Every test runs against the tracked example config — never the user's
personal config/career.toml (a post-/setup `pytest` must not go red from
someone's own resume keywords)."""
import pytest

from career_hunt import config as ch_config


@pytest.fixture(autouse=True)
def _pin_example_config(monkeypatch, tmp_path):
    monkeypatch.setattr(ch_config, "USER_PATH", tmp_path / "nonexistent-career.toml")
