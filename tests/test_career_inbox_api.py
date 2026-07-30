import pytest
from fastapi.testclient import TestClient

import db


def test_meta_carries_ats_watching_block(client):
    """The ATS page's 'watching' header needs: how many boards are swept, how
    many companies currently list internships, and when the last sweep ran."""
    m = client.get("/api/meta").json()
    ats = m["ats"]
    assert ats["boards"] >= 60                    # communal list is ~65 boards
    assert isinstance(ats["listings"], int) and isinstance(ats["companies"], int)
    assert "last_sweep" in ats                    # None until ats-pull has run


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
    return TestClient(app)


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
    assert client.post("/api/email-saved").status_code == 409
