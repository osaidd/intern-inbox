# tests/test_outlook_auth.py
"""Device-code OAuth without ever touching Microsoft: _post is injected."""
import json
import time

import pytest

from feeds import outlook_auth


@pytest.fixture
def cache(tmp_path, monkeypatch):
    path = tmp_path / "outlook_token.json"
    monkeypatch.setattr(outlook_auth, "TOKEN_PATH", path)
    return path


def test_client_id_env_beats_config(monkeypatch):
    class Cfg:
        outlook_client_id = "from-config"
    monkeypatch.delenv("OUTLOOK_CLIENT_ID", raising=False)
    assert outlook_auth.client_id(Cfg()) == "from-config"
    monkeypatch.setenv("OUTLOOK_CLIENT_ID", "from-env")
    assert outlook_auth.client_id(Cfg()) == "from-env"
    monkeypatch.delenv("OUTLOOK_CLIENT_ID", raising=False)
    assert outlook_auth.client_id(None) == ""


def test_start_device_flow(cache):
    def fake_post(url, data):
        assert url.endswith("/devicecode") and data["client_id"] == "cid"
        assert "IMAP.AccessAsUser.All" in data["scope"]
        return {"device_code": "dc", "user_code": "ABCD1234",
                "verification_uri": "https://microsoft.com/devicelogin",
                "interval": 5, "expires_in": 900}
    flow = outlook_auth.start_device_flow("cid", _post=fake_post)
    assert flow["user_code"] == "ABCD1234"
    with pytest.raises(RuntimeError, match="blocked"):
        outlook_auth.start_device_flow(
            "cid", _post=lambda u, d: {"error": "blocked",
                                       "error_description": "tenant blocked it"})


def test_poll_pending_then_connected(cache):
    assert outlook_auth.poll_once(
        "cid", "dc", _post=lambda u, d: {"error": "authorization_pending"}
    ) == {"status": "pending"}
    assert outlook_auth.poll_once(
        "cid", "dc", _post=lambda u, d: {"error": "slow_down"}
    ) == {"status": "pending"}
    out = outlook_auth.poll_once(
        "cid", "dc", _post=lambda u, d: {"access_token": "AT", "refresh_token": "RT",
                                         "expires_in": 3600})
    assert out == {"status": "connected"}
    saved = json.loads(cache.read_text())
    assert saved["access_token"] == "AT" and saved["refresh_token"] == "RT"
    assert outlook_auth.connected()
    err = outlook_auth.poll_once(
        "cid", "dc", _post=lambda u, d: {"error": "expired_token",
                                         "error_description": "code expired"})
    assert err["status"] == "error" and "expired" in err["message"]


def test_get_access_token_fresh_refresh_and_revoked(cache):
    assert outlook_auth.get_access_token("cid") is None      # never connected
    cache.write_text(json.dumps({"access_token": "AT1", "refresh_token": "RT1",
                                 "expires_at": time.time() + 600}))
    assert outlook_auth.get_access_token("cid") == "AT1"     # fresh: no network
    cache.write_text(json.dumps({"access_token": "AT1", "refresh_token": "RT1",
                                 "expires_at": time.time() - 10}))
    calls = {}

    def refresh_post(url, data):
        calls.update(data)
        return {"access_token": "AT2", "expires_in": 3600}   # MS may not rotate RT
    assert outlook_auth.get_access_token("cid", _post=refresh_post) == "AT2"
    assert calls["grant_type"] == "refresh_token" and calls["refresh_token"] == "RT1"
    assert json.loads(cache.read_text())["refresh_token"] == "RT1"  # carried forward
    cache.write_text(json.dumps({"access_token": "x", "refresh_token": "RT1",
                                 "expires_at": 0}))
    assert outlook_auth.get_access_token(
        "cid", _post=lambda u, d: {"error": "invalid_grant"}) is None
    outlook_auth.disconnect()
    assert not cache.exists() and not outlook_auth.connected()


def test_xoauth2_string():
    assert outlook_auth.xoauth2("a@b.co", "TOK") == b"user=a@b.co\x01auth=Bearer TOK\x01\x01"
