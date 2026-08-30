"""Hosted-demo mode (INTERN_INBOX_DEMO=1).

`career_inbox.web.DEMO` is read from the environment once at import, so the
fixtures set the env var and then `importlib.reload` the module. Teardown
reloads it again WITHOUT the var so every other test file keeps seeing a
normal, non-demo app.
"""
import importlib

import pytest
from fastapi.testclient import TestClient

import career_inbox.web
import db
from career_hunt import config as ch_config
from career_inbox import wizard

BLOCKED = "This is the public demo — install your own inbox to use this."

WIZARD_BODY = {"roles": ["swe_ai"], "size": "tiny", "custom_cap": None,
               "startups_only": True, "avoid": [], "email_address": "",
               "imap_pass": "", "force": False}


def _build(tmp_path, monkeypatch):
    """Reload the app module under the current env and hand back a client.
    Mirrors tests/test_wizard_api.py: scratch DB, no career.toml, no .env."""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    db.migrate()
    monkeypatch.setattr(ch_config, "USER_PATH", tmp_path / "career.toml")
    monkeypatch.setattr(wizard, "ENV_PATH", tmp_path / ".env")
    web = importlib.reload(career_inbox.web)
    cid = db.insert("companies", {"name": "Loomcraft AI", "name_key": "loomcraft ai",
                                  "stage": "seed", "headcount": 18,
                                  "enrich_status": "ok"})
    db.insert("opportunities", {"source": "ashby", "company": "Loomcraft AI",
                                "role": "AI Engineering Intern", "dedupe_hash": "d1",
                                "status": "new", "priority": "high", "company_id": cid})
    return web, TestClient(web.app, base_url="http://127.0.0.1",
                           follow_redirects=False)


@pytest.fixture()
def demo(tmp_path, monkeypatch):
    monkeypatch.setenv("INTERN_INBOX_DEMO", "1")
    web, client = _build(tmp_path, monkeypatch)
    assert web.DEMO is True
    yield client
    monkeypatch.delenv("INTERN_INBOX_DEMO", raising=False)
    importlib.reload(career_inbox.web)      # leave the module in normal mode


@pytest.fixture()
def live(tmp_path, monkeypatch):
    monkeypatch.delenv("INTERN_INBOX_DEMO", raising=False)
    web, client = _build(tmp_path, monkeypatch)
    assert web.DEMO is False
    yield client


# ---------------- demo on: the four owner-only writes are shut ----------------

@pytest.mark.parametrize("path, payload", [
    ("/api/email-saved", {}),
    ("/api/pull", {}),
    ("/api/wizard/complete", WIZARD_BODY),
    ("/api/add", [{"company": "Anon", "role": "Intern"}]),
])
def test_owner_writes_are_403_in_demo(demo, path, payload):
    r = demo.post(path, json=payload)
    assert r.status_code == 403
    assert r.json()["detail"] == BLOCKED


def test_meta_advertises_demo(demo):
    assert demo.get("/api/meta").json()["demo"] is True


def test_root_serves_the_app_without_a_config(demo):
    """No career.toml in the demo container's build context — the dashboard must
    still load instead of bouncing every visitor into the setup wizard."""
    r = demo.get("/")
    assert r.status_code == 200 and "Intern Inbox" in r.text


def test_triage_writes_stay_live_in_demo(demo):
    """Hearting rows is the whole point of the demo; the hourly reset cleans up."""
    assert demo.post("/api/jobs/1/status", json={"status": "shortlisted"}).status_code == 200
    assert demo.post("/api/jobs/1/note", json={"text": "nice"}).status_code == 200
    r = demo.post("/api/jobs/bulk", json={"ids": [1], "action": "kill"})
    assert r.status_code == 200 and r.json()["changed"] == 1


def test_reads_stay_open_in_demo(demo):
    assert demo.get("/api/jobs").status_code == 200
    assert demo.get("/api/jobs/1").status_code == 200
    assert demo.get("/api/offices").status_code == 200
    assert demo.get("/api/pull/status").status_code == 200


# ---------------- demo off: nothing about normal mode changed ----------------

def test_meta_has_no_demo_flag_when_off(live):
    assert live.get("/api/meta").json().get("demo") in (None, False)


def test_root_still_redirects_to_the_wizard_when_off(live):
    r = live.get("/")
    assert r.status_code == 302 and r.headers["location"] == "/welcome.html"


def test_owner_writes_are_not_403_when_off(live):
    """They may fail for their own reasons (nothing shortlisted, bad config) —
    they just must not be blocked by the demo gate."""
    assert live.post("/api/email-saved", json={}).status_code != 403
    assert live.post("/api/wizard/complete", json=WIZARD_BODY).status_code == 200
