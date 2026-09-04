import pytest

import db
from career_inbox import actions


@pytest.fixture()
def seed(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "life.db")
    db.migrate()
    for i, (comp, status) in enumerate([("Solva", "new"), ("Tessera", "new"),
                                        ("Auctor", "shortlisted")], 1):
        db.insert("opportunities", {"source": "github", "company": comp,
                                        "role": f"Role {i}", "dedupe_hash": f"h{i}",
                                        "status": status})
    return db


def _row(job_id):
    conn = db.connect()
    r = dict(conn.execute("SELECT * FROM opportunities WHERE id=?", (job_id,)).fetchone())
    conn.close()
    return r


def test_set_status_and_applied_stamp(seed):
    out = actions.set_status(1, "applied")
    assert out["status"] == "applied" and out["applied_date"]
    stamped = out["applied_date"]
    actions.set_status(1, "interviewing")
    actions.set_status(1, "applied")
    assert _row(1)["applied_date"] == stamped          # idempotent, not re-stamped


def test_set_status_rejects_garbage(seed):
    with pytest.raises(ValueError):
        actions.set_status(1, "hired")
    with pytest.raises(ValueError):
        actions.set_status(999, "dead")


def test_set_note_roundtrip_and_clear(seed):
    assert actions.set_note(2, "call back tue")["notes"] == "call back tue"
    assert actions.set_note(2, "   ")["notes"] is None


def test_bulk(seed):
    assert actions.bulk([1, 2], "kill") == 2
    assert _row(1)["status"] == "dead" and _row(2)["status"] == "dead"
    assert actions.bulk([3], "shortlist") == 1
    with pytest.raises(ValueError):
        actions.bulk([1], "explode")


def test_writes_nothing_else(seed):
    """The contract guard on the opportunities ROW: an action changes only
    status/applied_date/notes there. Stage/contact events are additive side
    tables by design, not row mutations."""
    before = _row(1)
    actions.set_status(1, "shortlisted")
    actions.set_note(1, "x")
    after = _row(1)
    diff = {k for k in before if before[k] != after[k]}
    assert diff <= {"status", "applied_date", "notes"}


# ---------------- stage events + suggestions + contacts (007) ----------------
def _events(job_id):
    conn = db.connect()
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM stage_events WHERE opportunity_id=? ORDER BY id", (job_id,))]
    conn.close()
    return rows


def _sug(sug_id):
    conn = db.connect()
    r = dict(conn.execute("SELECT * FROM suggestions WHERE id=?", (sug_id,)).fetchone())
    conn.close()
    return r


def _domains(company_id):
    conn = db.connect()
    rows = [(r["domain"], r["source"]) for r in conn.execute(
        "SELECT domain, source FROM company_domains WHERE company_id=?", (company_id,))]
    conn.close()
    return rows


def _seed_suggestion(kind="set_applied", opp=1, from_addr="recruiting@solva.com",
                     key="k1"):
    mid = db.insert("email_messages", {
        "dedupe_key": key, "gm_msgid": "g1", "message_id": f"<{key}@x>",
        "folder": "inbox", "from_addr": from_addr, "subject": "Thanks for applying",
        "sent_at": "2026-08-20T09:30:00", "classification": "application_received",
        "processed_at": "2026-08-21T08:00:00"})
    cid = db.insert("companies", {"name": f"Co-{key}", "name_key": f"co-{key}"})
    sid = db.insert("suggestions", {"kind": kind, "opportunity_id": opp,
                                    "company_id": cid, "email_message_id": mid,
                                    "evidence": "recruiting@solva.com · Thanks for applying · Aug 20",
                                    "created_at": "2026-08-21T08:00:00"})
    return sid, cid


def test_set_status_appends_stage_event(seed):
    actions.set_status(1, "applied")
    ev = _events(1)
    assert len(ev) == 1
    assert ev[0]["from_status"] == "new" and ev[0]["to_status"] == "applied"
    assert ev[0]["source"] == "ui" and ev[0]["occurred_at"]
    actions.set_status(1, "applied")                    # no-op: no second event
    assert len(_events(1)) == 1
    actions.set_status(1, "interviewing", source="skill", note="phone screen")
    ev = _events(1)
    assert len(ev) == 2
    assert ev[1]["source"] == "skill" and ev[1]["note"] == "phone screen"
    with pytest.raises(ValueError):
        actions.set_status(1, "offer", source="robot")


def test_applied_on_stamps_evidence_date(seed):
    out = actions.set_status(1, "applied", source="mail-confirm",
                             occurred_at="2026-08-20T10:00:00", applied_on="2026-08-20")
    assert out["applied_date"] == "2026-08-20"
    assert _events(1)[0]["occurred_at"] == "2026-08-20T10:00:00"
    actions.set_status(1, "interviewing")
    actions.set_status(1, "applied", applied_on="2026-09-01")
    assert _row(1)["applied_date"] == "2026-08-20"      # never re-stamped


def test_bulk_appends_events_and_keeps_count(seed):
    assert actions.bulk([1, 2, 999], "kill") == 2       # missing id not counted
    assert len(_events(1)) == 1 and len(_events(2)) == 1
    assert _events(1)[0]["to_status"] == "dead" and _events(1)[0]["source"] == "ui"
    assert actions.bulk([1], "kill") == 1               # row exists: counted, no event
    assert len(_events(1)) == 1


def test_accept_suggestion_full_flow(seed):
    sid, cid = _seed_suggestion()
    out = actions.accept_suggestion(sid)
    assert out["job"]["status"] == "applied"
    assert out["job"]["applied_date"] == "2026-08-20"   # evidence date, not today
    ev = _events(1)
    assert ev[-1]["source"] == "mail-confirm" and ev[-1]["suggestion_id"] == sid
    assert ev[-1]["occurred_at"] == "2026-08-20T09:30:00"
    sug = _sug(sid)
    assert sug["status"] == "accepted" and sug["resolved_at"]
    assert _domains(cid) == [("solva.com", "learned")]  # corporate sender learned
    with pytest.raises(ValueError):
        actions.accept_suggestion(sid)                  # already resolved


def test_accept_never_learns_shared_hosts(seed):
    sid, cid = _seed_suggestion(kind="set_rejected",
                                from_addr="no-reply@us.greenhouse.io", key="k2")
    actions.accept_suggestion(sid)
    assert _domains(cid) == []
    assert _row(1)["status"] == "rejected"


def test_dismiss_touches_nothing(seed):
    sid, _cid = _seed_suggestion(key="k3")
    before = _row(1)
    out = actions.dismiss_suggestion(sid)
    assert out["suggestion"]["status"] == "dismissed" and out["suggestion"]["resolved_at"]
    assert _row(1) == before and _events(1) == []
    with pytest.raises(ValueError):
        actions.dismiss_suggestion(sid)
    with pytest.raises(ValueError):
        actions.dismiss_suggestion(999)


def test_edit_job_identity_and_rank(seed, monkeypatch):
    from career_hunt import config as ch_config
    from feeds import jobspy_pull
    missing = seed.DB_PATH.parent / "no-user.toml"
    monkeypatch.setattr(ch_config, "USER_PATH", missing)
    monkeypatch.setattr(jobspy_pull, "USER_PATH", missing)
    out = actions.edit_job(1, {"company": "Ramp", "role": "AI Engineering Intern",
                               "url": "https://ramp.com/j/1",
                               "location": "New York, NY"})
    assert out["company"] == "Ramp" and out["location"] == "New York, NY"
    assert out["company_id"] is not None            # relinked to a real company row
    from career_hunt.models import dedupe_hash
    assert out["dedupe_hash"] == dedupe_hash("Ramp", "AI Engineering Intern",
                                             "https://ramp.com/j/1")
    assert out["priority"] in ("high", "medium", "low")
    # colliding with another row's identity refuses instead of forking
    actions.edit_job(2, {"role": "AI Engineering Intern"})
    with pytest.raises(ValueError, match="already tracked"):
        actions.edit_job(2, {"company": "Ramp", "url": "https://ramp.com/j/1"})
    with pytest.raises(ValueError, match="blank"):
        actions.edit_job(1, {"company": "  "})
    with pytest.raises(ValueError, match="http"):
        actions.edit_job(1, {"url": "javascript:alert(1)"})
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        actions.edit_job(1, {"posted_date": "yesterday"})
    with pytest.raises(ValueError, match="not editable"):
        actions.edit_job(1, {"status": "offer"})
    with pytest.raises(ValueError):
        actions.edit_job(999, {"company": "X"})


def test_edit_clears_optional_fields(seed, monkeypatch):
    from career_hunt import config as ch_config
    from feeds import jobspy_pull
    missing = seed.DB_PATH.parent / "no-user.toml"
    monkeypatch.setattr(ch_config, "USER_PATH", missing)
    monkeypatch.setattr(jobspy_pull, "USER_PATH", missing)
    actions.edit_job(1, {"location": "Hoboken, NJ", "salary_text": "$30/hr"})
    out = actions.edit_job(1, {"location": "", "salary_text": ""})
    assert out["location"] is None and out["salary_text"] is None


def test_set_next_action(seed):
    out = actions.set_next_action(1, "2026-09-12", note="  nudge the recruiter  ")
    assert out["next_action_date"] == "2026-09-12"
    assert out["next_action_note"] == "nudge the recruiter"
    out = actions.set_next_action(1, None)                 # clear wipes both
    assert out["next_action_date"] is None and out["next_action_note"] is None
    with pytest.raises(ValueError):
        actions.set_next_action(1, "next tuesday")
    with pytest.raises(ValueError):
        actions.set_next_action(999, "2026-09-12")


def test_log_contact(seed):
    out = actions.log_contact(opportunity_id=1, direction="out", note="cold email")
    c = out["contact"]
    assert c["channel"] == "manual" and c["created_by"] == "user"
    assert c["direction"] == "out" and c["occurred_at"] and c["snippet"] == "cold email"
    with pytest.raises(ValueError):
        actions.log_contact(direction="out")            # needs an id
    with pytest.raises(ValueError):
        actions.log_contact(opportunity_id=1, direction="sideways")
    with pytest.raises(ValueError):
        actions.log_contact(opportunity_id=999, direction="in")


def test_add_company_domain(seed):
    cid = db.insert("companies", {"name": "Ramp", "name_key": "ramp"})
    out = actions.add_company_domain(cid, "https://www.Ramp.com/about")
    assert out["domain"] == "ramp.com"
    assert _domains(cid) == [("ramp.com", "user")]
    with pytest.raises(ValueError):
        actions.add_company_domain(cid, "gmail.com")     # shared host
    with pytest.raises(ValueError):
        actions.add_company_domain(cid, "not a domain")
    with pytest.raises(ValueError):
        actions.add_company_domain(999, "acme.dev")
