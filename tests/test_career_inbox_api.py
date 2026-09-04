import pytest
from fastapi.testclient import TestClient

import db


def test_meta_carries_ats_watching_block(client, monkeypatch):
    """The ATS page's 'watching' header needs the board count and last sweep —
    decoupled from the real sources.toml so config edits can't break this test."""
    from career_inbox import web
    monkeypatch.setattr(web, "load_orgs", lambda: (["a", "b"], ["c"]))
    m = client.get("/api/meta").json()
    assert m["ats"]["boards"] == 3
    assert "last_sweep" in m["ats"]              # None until ats-pull has run
    # a broken sources config degrades the ledger, never 500s the dashboard
    def boom():
        raise RuntimeError("bad toml")
    monkeypatch.setattr(web, "load_orgs", boom)
    r = client.get("/api/meta")
    assert r.status_code == 200 and r.json()["ats"]["boards"] == 0


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "life.db")
    db.migrate()
    cid = db.insert("companies", {"name": "Solva", "name_key": "solva",
                                      "stage": "seed", "headcount": 30,
                                      "enrich_status": "ok", "lat": 40.74, "lon": -73.99})
    db.insert("opportunities", {"source": "github", "company": "Solva",
                                    "role": "AI Engineering Intern", "url": "https://x.co/1",
                                    "dedupe_hash": "h1", "priority": "high",
                                    "company_id": cid, "jd_text": "long jd text",
                                    "status": "new", "notes": "promising"})
    db.insert("opportunities", {"source": "jobspy", "company": "DeadCo",
                                    "role": "Ops Intern", "dedupe_hash": "h2",
                                    "status": "dead"})
    from career_inbox.web import app
    return TestClient(app, base_url="http://127.0.0.1")


def test_jobs_default_live_excludes_dead(client):
    d = client.get("/api/jobs").json()
    assert d["total"] == 1
    j = d["jobs"][0]
    assert j["company"] == "Solva" and j["stage"] == "seed" and j["headcount"] == 30
    assert j["jd_len"] == len("long jd text") and "jd_text" not in j
    assert j["family"] == "ai engineering" and j["notes"] == "promising"


def test_jobs_all_and_single_status(client):
    assert client.get("/api/jobs?statuses=all").json()["total"] == 2
    assert client.get("/api/jobs?statuses=dead").json()["total"] == 1


def test_job_detail_has_jd(client):
    jid = client.get("/api/jobs").json()["jobs"][0]["id"]
    assert client.get(f"/api/jobs/{jid}").json()["jd_text"] == "long jd text"
    assert client.get("/api/jobs/99999").status_code == 404


def test_add_url_endpoint(client, monkeypatch):
    from career_inbox import web
    seen = {}

    def fake(url, force=False, manual=None):
        seen.update(url=url, force=force, manual=manual)
        return {"outcome": "new", "id": 7, "company": "C", "role": "R",
                "priority": "medium", "warnings": []}
    monkeypatch.setattr(web.add_url, "add_from_url", fake)
    r = client.post("/api/add-url", json={"url": "https://x.co/j", "force": True,
                                          "manual": {"company": "C", "role": "R"}})
    assert r.status_code == 200 and r.json()["outcome"] == "new"
    assert seen == {"url": "https://x.co/j", "force": True,
                    "manual": {"company": "C", "role": "R"}}
    monkeypatch.setattr(web.add_url, "add_from_url",
                        lambda *a: {"outcome": "needs_confirm", "warnings": ["w"],
                                    "parsed": {}})
    assert client.post("/api/add-url",
                       json={"url": "https://x.co/j"}).json()["outcome"] == "needs_confirm"
    monkeypatch.setattr(web.add_url, "add_from_url",
                        lambda *a: {"outcome": "excluded", "message": "nope"})
    assert client.post("/api/add-url", json={"url": "https://x.co/j"}).status_code == 422
    # malformed bodies never reach the module
    assert client.post("/api/add-url", json={"nope": 1}).status_code == 422
    assert client.post("/api/add-url", json={"url": 5}).status_code == 422
    assert client.post("/api/add-url",
                       json={"url": "https://x.co", "manual": "x"}).status_code == 422


def test_add_url_real_chain_rejects_garbage(client):
    """Un-mocked BadUrl path — exercises the real module with zero network."""
    r = client.post("/api/add-url", json={"url": "not a url"})
    assert r.status_code == 422 and "look like a link" in r.json()["detail"]


def test_suggestion_accept_flow(client):
    jid = client.get("/api/jobs").json()["jobs"][0]["id"]
    mid = db.insert("email_messages", {
        "dedupe_key": "k1", "folder": "inbox", "from_addr": "recruiting@solva.com",
        "subject": "Thanks for applying", "sent_at": "2026-08-20T09:30:00",
        "classification": "application_received", "processed_at": "x"})
    sid = db.insert("suggestions", {"kind": "set_applied", "opportunity_id": jid,
                                    "email_message_id": mid, "evidence": "ev",
                                    "created_at": "x"})
    assert client.get("/api/meta").json()["counts"]["suggestions_open"] == 1
    lst = client.get("/api/suggestions").json()
    assert lst["total"] == 1
    s = lst["suggestions"][0]
    assert s["company"] == "Solva" and s["kind"] == "set_applied"
    assert s["from_addr"] == "recruiting@solva.com"
    r = client.post(f"/api/suggestions/{sid}/accept", json={})
    assert r.status_code == 200
    assert r.json()["job"]["status"] == "applied"
    assert r.json()["job"]["applied_date"] == "2026-08-20"   # evidence date
    assert client.get("/api/suggestions").json()["total"] == 0
    assert client.get("/api/meta").json()["counts"]["suggestions_open"] == 0
    assert client.post(f"/api/suggestions/{sid}/accept", json={}).status_code == 409
    assert client.post("/api/suggestions/999/accept", json={}).status_code == 404
    tl = client.get(f"/api/jobs/{jid}/timeline").json()
    stage = next(e for e in tl["events"] if e["kind"] == "stage")
    assert stage["to_status"] == "applied" and stage["source"] == "mail-confirm"


def test_suggestion_dismiss(client):
    jid = client.get("/api/jobs").json()["jobs"][0]["id"]
    sid = db.insert("suggestions", {"kind": "set_rejected", "opportunity_id": jid,
                                    "evidence": "ev", "created_at": "x"})
    before = client.get(f"/api/jobs/{jid}").json()["status"]
    assert client.post(f"/api/suggestions/{sid}/dismiss", json={}).status_code == 200
    assert client.get(f"/api/jobs/{jid}").json()["status"] == before
    assert client.post(f"/api/suggestions/{sid}/dismiss", json={}).status_code == 409


def test_suggestion_endpoints_reject_cross_site_content_types(client):
    """CSRF regression (security review 2026-09-04): the bodyless suggestion
    POSTs must enforce the JSON content-type gate — a cross-site form POST
    (which needs no CORS preflight) must never accept or dismiss a suggestion."""
    jid = client.get("/api/jobs").json()["jobs"][0]["id"]
    sid = db.insert("suggestions", {"kind": "set_applied", "opportunity_id": jid,
                                    "evidence": "ev", "created_at": "x"})
    for ep in ("accept", "dismiss"):
        r = client.post(f"/api/suggestions/{sid}/{ep}", data={"x": "1"})
        assert r.status_code == 415, ep
    conn = db.connect()
    sug = conn.execute("SELECT status FROM suggestions WHERE id=?", (sid,)).fetchone()
    opp = conn.execute("SELECT status FROM opportunities WHERE id=?", (jid,)).fetchone()
    conn.close()
    assert sug["status"] == "open" and opp["status"] == "new"   # no side effects


def test_contact_log_and_last_touch(client):
    jid = client.get("/api/jobs").json()["jobs"][0]["id"]
    r = client.post(f"/api/jobs/{jid}/contact",
                    json={"direction": "out", "note": "cold email",
                          "occurred_at": "2026-09-01T09:00:00"})
    assert r.status_code == 200 and r.json()["contact"]["snippet"] == "cold email"
    j = next(x for x in client.get("/api/jobs").json()["jobs"] if x["id"] == jid)
    assert j["last_out"] == "2026-09-01T09:00:00" and j["last_in"] is None
    client.post(f"/api/jobs/{jid}/contact",
                json={"direction": "in", "occurred_at": "2026-09-02T10:00:00"})
    tl = client.get(f"/api/jobs/{jid}/timeline").json()
    contacts = [e for e in tl["events"] if e["kind"] == "contact"]
    assert [c["direction"] for c in contacts] == ["in", "out"]   # newest first
    assert client.post(f"/api/jobs/{jid}/contact",
                       json={"direction": "sideways"}).status_code == 422
    assert client.post("/api/jobs/99999/contact",
                       json={"direction": "out"}).status_code == 404
    assert client.get("/api/jobs/99999/timeline").status_code == 404


def test_company_domain_endpoint(client):
    conn = db.connect()
    cid = conn.execute("SELECT id FROM companies").fetchone()["id"]
    conn.close()
    r = client.post(f"/api/companies/{cid}/domain", json={"domain": "solva.com"})
    assert r.status_code == 200 and r.json()["domain"] == "solva.com"
    assert client.post(f"/api/companies/{cid}/domain",
                       json={"domain": "gmail.com"}).status_code == 422
    assert client.post("/api/companies/999/domain",
                       json={"domain": "acme.dev"}).status_code == 404


def test_meta_mail_scan_state_and_consent_endpoints(client, monkeypatch, tmp_path):
    from career_inbox import web
    monkeypatch.setattr(web.pull, "MAIL_CONSENT", tmp_path / "consent")
    monkeypatch.setattr(web, "load_env", lambda: None)
    monkeypatch.delenv("CAREER_IMAP_PASS", raising=False)
    assert client.get("/api/meta").json()["mail_scan"]["state"] == "no-creds"
    monkeypatch.setenv("CAREER_IMAP_PASS", "pw")
    assert client.get("/api/meta").json()["mail_scan"]["state"] == "off"
    assert client.post("/api/mail-scan/enable", json={}).json()["mail_scan"] == "on"
    assert (tmp_path / "consent").exists()
    assert client.get("/api/meta").json()["mail_scan"]["state"] == "on"
    assert client.post("/api/mail-scan/disable", json={}).json()["mail_scan"] == "off"
    assert not (tmp_path / "consent").exists()
    assert client.get("/api/meta").json()["mail_scan"]["state"] == "off"


def test_update_endpoint(client, monkeypatch):
    from career_inbox import web
    monkeypatch.setattr(web.update, "run_update",
                        lambda: {"updated": True, "head": "abc", "output": "",
                                 "restart_needed": True})
    r = client.post("/api/update", json={})
    assert r.status_code == 200 and r.json()["restart_needed"] is True
    # blocked while a check runs (code must not be swapped under the feeds)
    monkeypatch.setitem(web.pull.STATE, "running", True)
    assert client.post("/api/update", json={}).status_code == 409
    monkeypatch.setitem(web.pull.STATE, "running", False)
    def blocked():
        raise web.update.UpdateBlocked("not a git checkout")
    monkeypatch.setattr(web.update, "run_update", blocked)
    assert client.post("/api/update", json={}).status_code == 409
    def failed():
        raise web.update.UpdateFailed("boom")
    monkeypatch.setattr(web.update, "run_update", failed)
    assert client.post("/api/update", json={}).status_code == 502


def test_meta_and_offices(client):
    m = client.get("/api/meta").json()
    assert m["counts"]["live"] == 1 and m["counts"]["high"] == 1
    assert "ai engineering" in m["families"]
    o = client.get("/api/offices").json()["offices"]
    assert o and o[0]["company"] == "Solva" and o[0]["roles"] == 1


def test_status_note_bulk_endpoints(client):
    jid = client.get("/api/jobs").json()["jobs"][0]["id"]
    r = client.post(f"/api/jobs/{jid}/status", json={"status": "shortlisted"})
    assert r.status_code == 200 and r.json()["status"] == "shortlisted"
    assert client.post(f"/api/jobs/{jid}/status", json={"status": "hired"}).status_code == 422
    assert client.post(f"/api/jobs/{jid}/note", json={"text": "ping"}).json()["notes"] == "ping"
    assert client.post("/api/jobs/bulk", json={"ids": [jid], "action": "kill"}).json()["changed"] == 1
    assert client.get("/api/jobs").json()["total"] == 0


def test_jobs_carry_term(client):
    """Internships have a season — the API derives it from title/JD per row."""
    client.post("/api/add", json=[{"company": "Vantable",
                                   "role": "Platform Intern (Summer 2027)",
                                   "url": "https://v.co/t", "location": "Brooklyn, NY"}])
    jobs = client.get("/api/jobs").json()["jobs"]
    by_co = {j["company"]: j for j in jobs}
    assert by_co["Vantable"]["term"] == "Summer 2027"
    assert by_co["Solva"]["term"] is None       # no season anywhere → honest None


def test_oversized_payloads_are_rejected_not_crashed(client):
    """Uncapped, a bulk `ids` list walks into SQLite's 32,767-variable ceiling and
    the OperationalError escapes as a 500; an uncapped note is a free memory sink.
    Both must come back as a clean 422 well before either limit."""
    jid = client.get("/api/jobs").json()["jobs"][0]["id"]
    assert client.post("/api/jobs/bulk",
                       json={"ids": [jid] * 501, "action": "kill"}).status_code == 422
    assert client.post(f"/api/jobs/{jid}/note",
                       json={"text": "x" * 10_001}).status_code == 422
    # the row is untouched: neither oversized request got as far as a write
    assert client.get("/api/jobs").json()["total"] == 1


def test_add_endpoint_inserts_and_dedupes(client):
    payload = [{"company": "Vantable", "role": "AI Engineering Intern", "url": "https://v.co/1",
                "location": "Brooklyn, NY", "stage_hint": "seed", "headcount_hint": 12}]
    assert client.post("/api/add", json=payload).json()["new"] == 1
    assert client.post("/api/add", json=payload).json()["dup"] == 1
    j = client.get("/api/jobs").json()["jobs"]
    v = next(x for x in j if x["company"] == "Vantable")
    assert v["source"] == "browser" and v["stage"] == "seed" and v["priority"] == "high"


def test_email_saved_409_when_empty(client, monkeypatch):
    client.post("/api/jobs/bulk",
                json={"ids": [x["id"] for x in client.get("/api/jobs").json()["jobs"]],
                      "action": "kill"})
    assert client.post("/api/email-saved", json={}).status_code == 409
