"""Wizard core: preset mapping, TOML emit, write refusal. All writes go to
tmp paths via monkeypatched module constants — never the real config/."""
import os
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


@pytest.fixture(autouse=True)
def _isolate_imap_env():
    """apply() with an email address now mutates os.environ directly (see
    wizard._write_env — it mirrors CAREER_IMAP_USER/PASS so a rotated
    credential reaches the running process without a restart). Snapshot both
    keys and restore exactly the pre-test state afterward so a test that
    writes credentials can never leak them into a later test."""
    keys = ("CAREER_IMAP_USER", "CAREER_IMAP_PASS")
    before = {k: os.environ[k] for k in keys if k in os.environ}
    yield
    for k in keys:
        os.environ.pop(k, None)
    os.environ.update(before)


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


def test_startups_only_keeps_blocklist_and_appends_avoid(paths):
    user, _ = paths
    example = ch_config.load(ch_config.EXAMPLE_PATH)
    wizard.apply(dict(BASE, startups_only=True, avoid=["BadCo"]), force=False)
    raw = tomllib.loads(user.read_text())
    excludes = raw["role"]["exclude_companies"]
    assert "Google" in excludes                                 # default blocklist retained
    assert len(excludes) >= len(example.exclude_companies)
    assert "BadCo" in excludes                                  # avoid still appended


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


def test_password_rotation_reaches_running_process_without_restart(paths):
    """Regression: envfile.load_env() seeds os.environ with setdefault, so it
    only ever runs once at boot. If a password was already loaded when the
    gear is used to rotate it, the file alone updating is not enough — the
    running process must see the new value immediately, or mail pulls keep
    failing against the revoked credential with no hint why."""
    user, env = paths
    env.write_text("CAREER_IMAP_USER=a@b.com\nCAREER_IMAP_PASS=old\n")
    os.environ["CAREER_IMAP_PASS"] = "old"
    wizard.apply(dict(BASE, email_address="a@b.com", imap_pass="new"), force=False)
    text = env.read_text()
    assert "CAREER_IMAP_PASS=new" in text                       # file rotated
    assert os.environ["CAREER_IMAP_PASS"] == "new"              # AND live in-process
    assert os.environ["CAREER_IMAP_USER"] == "a@b.com"           # user key mirrored too


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


def test_email_only_update_preserves_existing_password(paths):
    """Re-running with a new address but a blank imap_pass field (e.g. the user
    didn't re-type their app password) must update USER and leave the
    previously-saved PASS alone — never stale, never deleted."""
    user, env = paths
    env.write_text("CAREER_IMAP_USER=old@x.com\nCAREER_IMAP_PASS=keepme\n")
    wizard.apply(dict(BASE, email_address="new@x.com", imap_pass=""), force=False)
    text = env.read_text()
    assert "CAREER_IMAP_USER=new@x.com" in text                 # address updated
    assert "CAREER_IMAP_PASS=keepme" in text                    # old password preserved
    assert "CAREER_IMAP_USER=old@x.com" not in text


def test_validation_rejects_junk(paths):
    with pytest.raises(ValueError):
        wizard.apply(dict(BASE, roles=[]), force=False)
    with pytest.raises(ValueError):
        wizard.apply(dict(BASE, roles=["nope"]), force=False)
    with pytest.raises(ValueError):
        wizard.apply(dict(BASE, size="custom", custom_cap=3), force=False)


def test_control_char_in_avoid_rejected_and_existing_config_untouched(paths):
    user, _ = paths
    wizard.apply(dict(BASE), force=False)                       # existing wizard-written config
    before = user.read_text()
    with pytest.raises(ValueError):
        wizard.apply(dict(BASE, avoid=["Bad\nCo"]), force=False)
    assert user.read_text() == before                           # byte-identical, untouched
    assert not user.with_name("career.toml.tmp").exists()       # no leaked temp file


def test_control_char_in_email_address_rejected(paths):
    with pytest.raises(ValueError):
        wizard.apply(dict(BASE, email_address="a@b.com\r\nX-Injected: 1"), force=False)


def test_atomic_write_happy_path_round_trips_with_no_leftover_temp(paths):
    user, _ = paths
    st = wizard.apply(dict(BASE), force=False)
    assert st == {"configured": True, "wizard_written": True}
    cfg = ch_config.load(user)
    assert cfg.company.hard_cap_headcount == 50
    assert not user.with_name("career.toml.tmp").exists()       # staging file swapped away


def test_presets_never_target_an_excluded_title():
    """No preset may advertise a target_title that the example config's own
    [role].exclude_keywords would filter out at ingest (score.matches() does a
    raw substring check against the job title) — a preset that collides would
    silently kill the very postings it exists to surface. Regression coverage
    for bizops's former 'chief of staff intern' vs. the 'staff' keyword."""
    presets = wizard.load_presets()
    excl = [k.lower() for k in ch_config.load(ch_config.EXAMPLE_PATH).exclude_keywords]
    for key, preset in presets.items():
        for title in preset["target_titles"]:
            t = title.lower()
            hits = [k for k in excl if k in t]
            assert not hits, f"{key} target_title {title!r} collides with exclude_keyword(s) {hits}"


def test_load_presets_contract():
    """Task 3's contract: load_presets() -> {key: {label, profile_keywords,
    target_titles}} for exactly the five curated bundles."""
    presets = wizard.load_presets()
    assert set(presets.keys()) == {"swe_ai", "product", "data", "gtm_growth", "bizops"}
    for key, preset in presets.items():
        assert preset.get("label"), key
        assert preset.get("profile_keywords"), key
        assert preset.get("target_titles"), key


# ---------------- prefill + reply-scan consent (spec 2026-09-04) ----------------
def _isolate_consent(tmp_path, monkeypatch):
    from career_inbox import pull
    marker = tmp_path / "mail_scan_enabled"
    monkeypatch.setattr(pull, "MAIL_CONSENT", marker)
    return marker


def test_prefill_round_trip(paths, tmp_path, monkeypatch):
    _isolate_consent(tmp_path, monkeypatch)
    assert wizard.prefill() is None                       # no config yet
    wizard.apply(dict(BASE, roles=["swe_ai", "product"], size="mid",
                      avoid=["Acme Corp"], email_address="me@gmail.com",
                      imap_pass="abcd efgh ijkl mnop", mail_scan=True), force=False)
    pf = wizard.prefill()
    assert {"swe_ai", "product"} <= set(pf["roles"])
    assert pf["size"] == "mid" and pf["custom_cap"] is None
    assert pf["startups_only"] is True and pf["avoid"] == ["Acme Corp"]
    assert pf["email_address"] == "me@gmail.com"
    assert pf["imap_saved"] is True and pf["mail_scan"] is True
    assert "abcd" not in str(pf)                          # never the secret itself


def test_prefill_custom_cap_foreign_and_broken(paths, tmp_path, monkeypatch):
    _isolate_consent(tmp_path, monkeypatch)
    user, _ = paths
    wizard.apply(dict(BASE, size="custom", custom_cap=70), force=False)
    pf = wizard.prefill()
    assert pf["size"] == "custom" and pf["custom_cap"] == 70
    # a foreign (/setup-style) config still prefills best-effort, never raises
    user.write_text(ch_config.EXAMPLE_PATH.read_text())
    pf = wizard.prefill()
    assert pf is not None and pf["startups_only"] is True and pf["avoid"] == []
    user.write_text("not [valid toml")
    assert wizard.prefill() is None


def test_mail_scan_checkbox_controls_consent_marker(paths, tmp_path, monkeypatch):
    marker = _isolate_consent(tmp_path, monkeypatch)
    wizard.apply(dict(BASE, mail_scan=True), force=False)
    assert marker.exists()
    wizard.apply(dict(BASE, mail_scan=False), force=False)   # the form is the truth
    assert not marker.exists()
    marker.write_text("x")
    wizard.apply(dict(BASE), force=False)                    # absent key: untouched
    assert marker.exists()


def test_imap_saved_false_without_password(paths, tmp_path, monkeypatch):
    _isolate_consent(tmp_path, monkeypatch)
    wizard.apply(dict(BASE, email_address="me@gmail.com"), force=False)
    assert wizard.prefill()["imap_saved"] is False
