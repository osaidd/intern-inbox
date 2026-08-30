import pytest
from fastapi.testclient import TestClient

import db
from career_hunt import config as ch_config
from career_inbox import wizard


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    db.migrate()
    monkeypatch.setattr(ch_config, "USER_PATH", tmp_path / "career.toml")
    monkeypatch.setattr(wizard, "ENV_PATH", tmp_path / ".env")
    from career_inbox.web import app
    return TestClient(app, base_url="http://127.0.0.1", follow_redirects=False)


BODY = {"roles": ["swe_ai"], "size": "tiny", "custom_cap": None,
        "startups_only": True, "avoid": [], "email_address": "",
        "imap_pass": "", "force": False}


def test_root_redirects_to_welcome_when_unconfigured(client):
    r = client.get("/")
    assert r.status_code == 302 and r.headers["location"] == "/welcome.html"


def test_state_lists_presets(client):
    s = client.get("/api/wizard/state").json()
    assert s["configured"] is False
    assert s["presets"]["swe_ai"]["label"]
    assert s["sizes"] == ["tiny", "small", "mid", "any"]


def test_complete_writes_config_then_root_serves_app(client):
    r = client.post("/api/wizard/complete", json=BODY)
    assert r.status_code == 200 and r.json()["configured"] is True
    r = client.get("/")
    assert r.status_code == 200 and "Intern Inbox" in r.text


def test_complete_conflicts_on_foreign_config(client):
    ch_config.USER_PATH.write_text("# by /setup\n")
    assert client.post("/api/wizard/complete", json=BODY).status_code == 409
    ok = client.post("/api/wizard/complete", json=dict(BODY, force=True))
    assert ok.status_code == 200


def test_complete_validates(client):
    assert client.post("/api/wizard/complete",
                       json=dict(BODY, roles=[])).status_code == 422
    assert client.post("/api/wizard/complete",
                       json=dict(BODY, size="custom")).status_code == 422


def test_complete_requires_json_content_type(client):
    r = client.post("/api/wizard/complete", content=b"x=1",
                    headers={"content-type": "application/x-www-form-urlencoded"})
    assert r.status_code == 415
