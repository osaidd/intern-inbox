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
    """The contract guard: an action changes only status/applied_date/notes."""
    before = _row(1)
    actions.set_status(1, "shortlisted")
    actions.set_note(1, "x")
    after = _row(1)
    diff = {k for k in before if before[k] != after[k]}
    assert diff <= {"status", "applied_date", "notes"}
