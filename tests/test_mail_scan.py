# tests/test_mail_scan.py
"""The mail-scan feed's binding contracts: readonly IMAP, server-side scoped
searches (privacy), opportunities byte-untouched, idempotency, consent gates."""
import re
from email.message import EmailMessage

import pytest

import db
from career_hunt import config as ch_config
from career_hunt.mail_classify import ATS_DOMAINS, LINKEDIN_SENDERS
from feeds import mail_scan


def _msg(from_, to, subject, body, headers=None):
    m = EmailMessage()
    m["From"] = from_
    m["To"] = to
    m["Subject"] = subject
    m["Date"] = "Tue, 01 Sep 2026 10:30:00 -0400"
    m["Message-ID"] = f"<{abs(hash((from_, to, subject)))}@x>"
    for k, v in (headers or {}).items():
        m[k] = v
    m.set_content(body)
    return m


class FakeImap:
    """Folder-aware fake: search narrows by FROM/TO substring, select must be
    readonly, fetch must PEEK. Records every search for the privacy test."""

    def __init__(self, mailbox):
        self.mailbox = mailbox          # {"INBOX": [...], "sent": [...]}
        self.searches = []              # (folder, criteria)
        self.folder = None
        self.logged_out = False

    def login(self, user, password):
        return ("OK", [b""])

    def list(self):
        return ("OK", [b'(\\HasNoChildren) "/" "INBOX"',
                       b'(\\HasNoChildren \\Sent) "/" "[Gmail]/Sent Mail"'])

    def select(self, folder, readonly=False):
        assert readonly is True, "mail scan must never open a folder read-write"
        self.folder = "sent" if "Sent" in str(folder) else "INBOX"
        return ("OK", [b"1"])

    def search(self, charset, criteria):
        self.searches.append((self.folder, criteria))
        m = re.search(r'\((FROM|TO) "([^"]+)"', criteria)
        kind, needle = m.group(1), m.group(2).lower()
        hits = []
        for i, msg in enumerate(self.mailbox.get(self.folder, []), 1):
            hay = str(msg.get("From" if kind == "FROM" else "To", "")).lower()
            if needle in hay:
                hits.append(str(i).encode())
        return ("OK", [b" ".join(hits)])

    def fetch(self, num, spec):
        i = int(num) - 1
        msg = self.mailbox[self.folder][i]
        gmid = (1000 if self.folder == "INBOX" else 2000) + i
        if "X-GM-MSGID" in spec and "BODY" not in spec:
            return ("OK", [f"{int(num)} (X-GM-MSGID {gmid})".encode()])
        assert "BODY.PEEK[]" in spec, "must fetch with PEEK (never sets \\Seen)"
        return ("OK", [(f"{int(num)} (X-GM-MSGID {gmid} BODY[] {{1}}".encode(),
                        msg.as_bytes()), b")"])

    def logout(self):
        self.logged_out = True
        return ("BYE", [b""])


INBOX = [
    _msg("Greenhouse <no-reply@us.greenhouse.io>", "me@gmail.com",
         "Thank you for applying to Tessera",
         "Your application to Tessera has been received."),
    _msg("Alex <alex@ramp.com>", "me@gmail.com",
         "Interview availability",
         "Can you share your availability for a phone screen?"),
    _msg("Alex <alex@ramp.com>", "me@gmail.com",
         "Update on your application",
         "Unfortunately we will not be moving forward."),
    _msg("Ramp Updates <news@ramp.com>", "me@gmail.com",
         "October product newsletter", "Big launches!",
         headers={"List-Unsubscribe": "<mailto:u@ramp.com>"}),
    _msg("LinkedIn <jobs-noreply@linkedin.com>", "me@gmail.com",
         "Osaid, your application was sent to Ramp", "Good luck!"),
    _msg("Rando <hi@randomco.dev>", "me@gmail.com",
         "Interview tomorrow?", "unrelated mail that must never be fetched"),
]
SENT = [
    _msg("me@gmail.com", "recruiting@ramp.com", "Intro from an intern candidate",
         "I'd love to work on your platform team."),
    _msg("me@gmail.com", "me@gmail.com", "note to self", "remember to follow up"),
    _msg("me@gmail.com", "friend@example.com", "dinner?", "personal mail"),
]


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "life.db")
    monkeypatch.setattr(ch_config, "USER_PATH", tmp_path / "none.toml")
    db.migrate()
    monkeypatch.setenv("CAREER_IMAP_USER", "me@gmail.com")
    monkeypatch.setenv("CAREER_IMAP_PASS", "app-password")
    ramp = db.insert("companies", {"name": "Ramp", "name_key": "ramp",
                                   "website": "https://ramp.com"})
    tess = db.insert("companies", {"name": "Tessera", "name_key": "tessera"})
    newco = db.insert("companies", {"name": "NewCo", "name_key": "newco",
                                    "website": "https://newco.dev"})
    db.insert("opportunities", {"source": "ashby", "company": "Ramp",
                                "role": "Software Engineering Intern",
                                "dedupe_hash": "h1", "status": "applied",
                                "company_id": ramp})
    db.insert("opportunities", {"source": "paste", "company": "Tessera",
                                "role": "Data Intern", "dedupe_hash": "h2",
                                "status": "shortlisted", "company_id": tess,
                                "url": "https://careers.tessera.dev/roles/9"})
    db.insert("opportunities", {"source": "github", "company": "NewCo",
                                "role": "Ops Intern", "dedupe_hash": "h3",
                                "status": "new", "company_id": newco})
    return {"ramp": ramp, "tess": tess, "newco": newco}


def _snapshot_opps():
    conn = db.connect()
    rows = [tuple(r) for r in conn.execute("SELECT * FROM opportunities ORDER BY id")]
    conn.close()
    return rows


def _count(table, where="1=1"):
    conn = db.connect()
    n = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}").fetchone()[0]
    conn.close()
    return n


def test_end_to_end_scan(env):
    imap = FakeImap({"INBOX": INBOX, "sent": SENT})
    before = _snapshot_opps()
    stats = mail_scan.main(_imap=imap)
    # CONTRACT: the feed never touches opportunities — byte-identical
    assert _snapshot_opps() == before
    assert imap.logged_out
    # ledger: 5 inbox msgs (ATS, interview, rejection, newsletter, LinkedIn) + 1 sent
    assert stats["new_msgs"] == 6 and _count("email_messages") == 6
    # contacts: 4 inbound (newsletter is bulk -> ledger only) + 1 outbound
    assert stats["contacts"] == 5
    assert _count("contact_events", "direction='in'") == 4
    assert _count("contact_events", "direction='out'") == 1
    # suggestions: Tessera set_applied + Ramp set_interviewing + Ramp set_rejected;
    # the LinkedIn "application sent to Ramp" is NOT eligible (already applied)
    conn = db.connect()
    sugs = {(r["kind"], r["opportunity_id"]) for r in
            conn.execute("SELECT kind, opportunity_id FROM suggestions "
                         "WHERE status='open'")}
    out = conn.execute("SELECT company_id, subject, snippet FROM contact_events "
                       "WHERE direction='out'").fetchone()
    conn.close()
    assert sugs == {("set_applied", 2), ("set_interviewing", 1), ("set_rejected", 1)}
    assert stats["suggestions"] == 3
    assert out["company_id"] == env["ramp"]
    assert out["subject"].startswith("Intro") and len(out["snippet"] or "") <= 200
    # one ok run_log row
    conn = db.connect()
    runs = conn.execute("SELECT skill, status FROM run_log").fetchall()
    conn.close()
    assert [(r["skill"], r["status"]) for r in runs] == [("mail-scan", "ok")]


def test_privacy_searches_are_scoped(env):
    """Every IMAP search must name only ATS/LinkedIn senders or tracked-company
    domains; the Sent pass must equal the worked-pipeline domain set exactly."""
    imap = FakeImap({"INBOX": INBOX, "sent": SENT})
    mail_scan.main(_imap=imap)
    allowed_from = ATS_DOMAINS | LINKEDIN_SENDERS | {"ramp.com", "tessera.dev"}
    sent_domains = set()
    for folder, crit in imap.searches:
        m = re.search(r'\((FROM|TO) "([^"]+)" SINCE "[^"]+"\)$', crit)
        assert m, f"unexpected criteria shape: {crit}"
        kind, needle = m.groups()
        if folder == "INBOX":
            assert kind == "FROM" and needle in allowed_from, crit
        else:
            assert kind == "TO", crit
            sent_domains.add(needle)
    # worked pipeline only: NewCo (status 'new') must never be searched for
    assert sent_domains == {"ramp.com", "tessera.dev"}
    assert not any("newco" in c for _f, c in imap.searches)
    assert not any("randomco" in c for _f, c in imap.searches)


def test_second_run_is_idempotent(env):
    mail_scan.main(_imap=FakeImap({"INBOX": INBOX, "sent": SENT}))
    counts = (_count("email_messages"), _count("contact_events"), _count("suggestions"))
    stats2 = mail_scan.main(_imap=FakeImap({"INBOX": INBOX, "sent": SENT}))
    assert (_count("email_messages"), _count("contact_events"),
            _count("suggestions")) == counts
    assert stats2["new_msgs"] == 0 and stats2["suggestions"] == 0


def test_dry_run_writes_nothing(env):
    stats = mail_scan.main(dry_run=True, _imap=FakeImap({"INBOX": INBOX, "sent": SENT}))
    assert stats["new_msgs"] > 0
    assert _count("email_messages") == 0 and _count("contact_events") == 0
    assert _count("suggestions") == 0 and _count("run_log") == 0


def test_expire_satisfied_dismisses_handled_rows(env):
    db.insert("suggestions", {"kind": "set_applied", "opportunity_id": 1,
                              "company_id": env["ramp"], "evidence": "stale",
                              "created_at": "2026-08-01"})   # row 1 already applied
    mail_scan.main(_imap=FakeImap({"INBOX": [], "sent": []}))
    conn = db.connect()
    r = conn.execute("SELECT status FROM suggestions WHERE evidence='stale'").fetchone()
    conn.close()
    assert r["status"] == "dismissed"


def test_not_configured_logs_partial(env, monkeypatch):
    monkeypatch.delenv("CAREER_IMAP_PASS")
    monkeypatch.setattr(mail_scan, "load_env", lambda: None)   # real .env must not leak in
    stats = mail_scan.main(_imap=FakeImap({"INBOX": [], "sent": []}))
    assert stats["new_msgs"] == 0
    conn = db.connect()
    r = conn.execute("SELECT status, summary FROM run_log").fetchone()
    conn.close()
    assert r["status"] == "partial" and "app password" in r["summary"]


def test_disabled_in_config_logs_partial(env, tmp_path, monkeypatch):
    toml = ch_config.EXAMPLE_PATH.read_text()
    assert "[mail_scan]" in toml          # the example documents the section
    toml = re.sub(r"(\[mail_scan\][^\[]*?)enabled = true", r"\1enabled = false",
                  toml, count=1, flags=re.S)
    user_toml = tmp_path / "career.toml"
    user_toml.write_text(toml)
    monkeypatch.setattr(ch_config, "USER_PATH", user_toml)
    stats = mail_scan.main(_imap=FakeImap({"INBOX": INBOX, "sent": SENT}))
    assert stats["new_msgs"] == 0 and _count("email_messages") == 0
    conn = db.connect()
    r = conn.execute("SELECT status, summary FROM run_log").fetchone()
    conn.close()
    assert r["status"] == "partial" and "disabled" in r["summary"]


def test_domain_seeding(env):
    conn = db.connect()
    mail_scan.sync_company_domains(conn)
    doms = {(r["domain"], r["source"]) for r in
            conn.execute("SELECT domain, source FROM company_domains")}
    assert ("ramp.com", "website") in doms
    assert ("tessera.dev", "url") in doms       # from the posting URL host
    assert ("newco.dev", "website") in doms     # seeded, but filtered by WORKED later
    assert mail_scan.sync_company_domains(conn) == 0    # rerun adds nothing
    assert mail_scan.pipeline_domains(conn) == {"ramp.com": env["ramp"],
                                                "tessera.dev": env["tess"]}
    conn.close()


def test_pull_connector_gates(tmp_path, monkeypatch):
    from career_inbox import pull
    monkeypatch.setattr(pull, "MAIL_CONSENT", tmp_path / "consent")
    monkeypatch.setattr(pull, "MAIL_STAMP", tmp_path / "stamp")
    # no consent marker -> soft skip with the exact off message
    assert pull._mail_scan() == (None, "off — enable reply tracking in the app")
    (tmp_path / "consent").write_text("")
    # consent + due + no password -> not-configured skip; the daily stamp is NOT
    # burned (adding the password later today must still scan on the next check)
    monkeypatch.delenv("CAREER_IMAP_PASS", raising=False)
    monkeypatch.setattr("feeds.envfile.load_env", lambda: None)
    out = pull._mail_scan()
    assert out == (None, "not configured (no Gmail app password — see SETUP.md)")
    assert not (tmp_path / "stamp").exists()
    # configured -> runs and writes the stamp; a second call hits the daily budget
    monkeypatch.setenv("CAREER_IMAP_PASS", "pw")
    monkeypatch.setattr("feeds.mail_scan.main",
                        lambda trigger="manual": {"new": 0})
    assert pull._mail_scan() == {"new": 0}
    assert (tmp_path / "stamp").exists()
    assert pull._mail_scan() is None
