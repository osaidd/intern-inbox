import db
from career_inbox import pull


def test_full_check_isolated_and_logged(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "life.db")
    db.migrate()
    monkeypatch.setattr(pull, "STAMP", tmp_path / "jobspy_last_pull")
    calls = []
    monkeypatch.setattr(pull, "CONNECTORS", [
        ("linkedin", lambda: calls.append("li") or {"new": 2}),
        ("github", lambda: (_ for _ in ()).throw(RuntimeError("boom"))),
    ])
    out = pull.full_check(trigger="test")
    assert calls == ["li"]
    assert out["steps"]["linkedin"].startswith("ok")
    assert out["steps"]["github"].startswith("error")
    conn = db.connect()
    row = conn.execute("SELECT skill, status, summary FROM run_log "
                       "ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    assert row["skill"] == "career-inbox-check"
    assert row["status"] == "partial"          # one connector failed, one succeeded
    assert "github=error" in row["summary"]


def test_jobspy_daily_stamp(tmp_path, monkeypatch):
    monkeypatch.setattr(pull, "STAMP", tmp_path / "stamp")
    assert pull.jobspy_due() is True
    pull.write_stamp()
    assert pull.jobspy_due() is False


def test_ats_connector_respects_daily_stamp(tmp_path, monkeypatch):
    monkeypatch.setattr(pull, "ATS_STAMP", tmp_path / "ats_stamp")
    calls = []
    monkeypatch.setattr(pull, "_ats_main", lambda: calls.append(1) or {"new": 3})
    assert pull._ats() == {"new": 3}          # first run of the day → feed runs
    assert pull._ats() is None                # same day → skipped (daily budget)
    assert calls == [1]
    assert ("ats", pull._ats) in pull.CONNECTORS
