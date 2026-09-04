# tests/test_mail_auth.py
"""Provider routing: ready() gates and connect() auth shapes, no network."""
import json
import time

import pytest

from feeds import mail_auth, outlook_auth


class Cfg:
    def __init__(self, provider="gmail", host="", cid=""):
        self.mail_provider = provider
        self.mail_imap_host = host
        self.outlook_client_id = cid


class FakeImap:
    def __init__(self):
        self.logins, self.auths = [], []
        self.logged_out = False

    def login(self, user, password):
        self.logins.append((user, password))
        return ("OK", [b""])

    def authenticate(self, mech, authobject):
        self.auths.append((mech, authobject(b"")))
        return ("OK", [b""])

    def logout(self):
        self.logged_out = True


@pytest.fixture
def outlook_cache(tmp_path, monkeypatch):
    path = tmp_path / "tok.json"
    monkeypatch.setattr(outlook_auth, "TOKEN_PATH", path)
    return path


def test_ready_matrix(monkeypatch, outlook_cache):
    monkeypatch.delenv("CAREER_IMAP_PASS", raising=False)
    monkeypatch.delenv("CAREER_IMAP_HOST", raising=False)
    monkeypatch.delenv("OUTLOOK_CLIENT_ID", raising=False)
    ok, reason = mail_auth.ready(Cfg("gmail"))
    assert not ok and "CAREER_IMAP_PASS" in reason        # historical wording kept
    monkeypatch.setenv("CAREER_IMAP_PASS", "pw")
    assert mail_auth.ready(Cfg("gmail")) == (True, "")
    ok, reason = mail_auth.ready(Cfg("imap"))
    assert not ok and "IMAP host" in reason
    assert mail_auth.ready(Cfg("imap", host="imap.school.edu")) == (True, "")
    ok, reason = mail_auth.ready(Cfg("outlook"))
    assert not ok and "client id" in reason
    ok, reason = mail_auth.ready(Cfg("outlook", cid="cid"))
    assert not ok and "not connected" in reason
    outlook_cache.write_text(json.dumps({"access_token": "AT", "refresh_token": "RT",
                                         "expires_at": time.time() + 600}))
    assert mail_auth.ready(Cfg("outlook", cid="cid")) == (True, "")


def test_connect_gmail_and_imap(monkeypatch):
    monkeypatch.setenv("CAREER_IMAP_PASS", "app-pass")
    fake = FakeImap()
    out = mail_auth.connect("me@gmail.com", Cfg("gmail"), _imap=fake)
    assert out is fake and fake.logins == [("me@gmail.com", "app-pass")]
    fake = FakeImap()
    mail_auth.connect("me@school.edu", Cfg("imap", host="imap.school.edu"), _imap=fake)
    assert fake.logins == [("me@school.edu", "app-pass")]


def test_connect_outlook_xoauth2(monkeypatch, outlook_cache):
    monkeypatch.delenv("OUTLOOK_CLIENT_ID", raising=False)
    outlook_cache.write_text(json.dumps({"access_token": "TOK", "refresh_token": "RT",
                                         "expires_at": time.time() + 600}))
    fake = FakeImap()
    mail_auth.connect("me@school.edu", Cfg("outlook", cid="cid"), _imap=fake)
    assert fake.logins == []
    mech, blob = fake.auths[0]
    assert mech == "XOAUTH2"
    assert blob == b"user=me@school.edu\x01auth=Bearer TOK\x01\x01"


def test_connect_raises_the_ready_reason(monkeypatch, outlook_cache):
    monkeypatch.delenv("CAREER_IMAP_PASS", raising=False)
    with pytest.raises(mail_auth.MailNotReady, match="app password"):
        mail_auth.connect("u", Cfg("gmail"), _imap=FakeImap())
    with pytest.raises(mail_auth.MailNotReady, match="not connected"):
        mail_auth.connect("u", Cfg("outlook", cid="cid"), _imap=FakeImap())
