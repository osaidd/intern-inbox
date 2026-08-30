"""Wizard core: preset mapping, TOML emit, write refusal. All writes go to
tmp paths via monkeypatched module constants — never the real config/."""
import tomllib

import pytest

from career_hunt import config as ch_config
from career_hunt.score import company_tier
from career_inbox import wizard


@pytest.fixture()
def paths(tmp_path, monkeypatch):
    user = tmp_path / "career.toml"
    env = tmp_path / ".env"
    monkeypatch.setattr(ch_config, "USER_PATH", user)
    monkeypatch.setattr(wizard, "ENV_PATH", env)
    return user, env


BASE = {"roles": ["swe_ai"], "size": "tiny", "custom_cap": None,
        "startups_only": True, "avoid": [], "email_address": "", "imap_pass": ""}


def test_apply_writes_loadable_config_with_marker(paths):
    user, _ = paths
    st = wizard.apply(dict(BASE), force=False)
    assert st == {"configured": True, "wizard_written": True}
    assert user.read_text().startswith(wizard.WIZARD_MARKER)
    cfg = ch_config.load(user)                      # loader accepts the emit
    assert cfg.company.hard_cap_headcount == 50


@pytest.mark.parametrize("size,cap,late_tier", [
    ("tiny", 50, "dead"), ("small", 100, "dead"),
    ("mid", 500, "unknown"), ("any", 10**9, "unknown"),
])
def test_size_presets_map_to_tier_semantics(paths, size, cap, late_tier):
    user, _ = paths
    wizard.apply(dict(BASE, size=size), force=False)
    cfg = ch_config.load(user)
    assert cfg.company.hard_cap_headcount == cap
    assert company_tier("seed", None, cfg) == "tier1"          # unknown size never dead
    assert company_tier("seed", cap + 1, cfg) == "dead"        # confirmed over-cap dies
    assert company_tier("series c", 40, cfg) == late_tier      # late-stage rule per preset


def test_custom_cap(paths):
    user, _ = paths
    wizard.apply(dict(BASE, size="custom", custom_cap=70), force=False)
    cfg = ch_config.load(user)
    assert cfg.company.hard_cap_headcount == 70
    assert cfg.company.tier1_max_headcount == 70


def test_roles_union_dedupes_and_mirrors_scoring(paths):
    user, _ = paths
    wizard.apply(dict(BASE, roles=["swe_ai", "data"]), force=False)
    raw = tomllib.loads(user.read_text())
    assert raw["role"]["profile_keywords"] == raw["scoring"]["profile_keywords"]
    assert raw["role"]["target_titles"] == raw["scoring"]["target_titles"]
    kws = raw["role"]["profile_keywords"]
    assert "python" in kws and kws.count("python") == 1        # union, deduped


def test_show_everything_clears_blocklist_and_avoid_appends(paths):
    user, _ = paths
    wizard.apply(dict(BASE, startups_only=False, avoid=["BadCo"]), force=False)
    raw = tomllib.loads(user.read_text())
    assert raw["role"]["exclude_companies"] == ["BadCo"]


def test_email_written_to_config_and_env(paths):
    user, env = paths
    wizard.apply(dict(BASE, email_address="a@b.com", imap_pass="abcd efgh ijkl mnop"),
                 force=False)
    raw = tomllib.loads(user.read_text())
    assert raw["email"]["to"] == "a@b.com" and raw["email"]["smtp_user"] == "a@b.com"
    assert raw["email"]["enabled"] is False                    # digests stay off
    text = env.read_text()
    assert "CAREER_IMAP_PASS=abcdefghijklmnop" in text          # spaces stripped
    assert "CAREER_IMAP_USER=a@b.com" in text


def test_refuses_non_wizard_config_without_force(paths):
    user, _ = paths
    user.write_text("# hand-written by /setup\n[hunt]\n")
    with pytest.raises(wizard.WizardConflict):
        wizard.apply(dict(BASE), force=False)
    wizard.apply(dict(BASE), force=True)                       # explicit force wins
    assert user.read_text().startswith(wizard.WIZARD_MARKER)


def test_rerun_over_wizard_file_needs_no_force(paths):
    wizard.apply(dict(BASE), force=False)
    wizard.apply(dict(BASE, size="small"), force=False)        # no exception


def test_env_update_preserves_other_keys(paths):
    user, env = paths
    env.write_text("OTHER=1\nCAREER_IMAP_PASS=old\n")
    wizard.apply(dict(BASE, email_address="a@b.com", imap_pass="new"), force=False)
    text = env.read_text()
    assert "OTHER=1" in text and "CAREER_IMAP_PASS=new" in text
    assert "CAREER_IMAP_PASS=old" not in text


def test_validation_rejects_junk(paths):
    with pytest.raises(ValueError):
        wizard.apply(dict(BASE, roles=[]), force=False)
    with pytest.raises(ValueError):
        wizard.apply(dict(BASE, roles=["nope"]), force=False)
    with pytest.raises(ValueError):
        wizard.apply(dict(BASE, size="custom", custom_cap=3), force=False)
