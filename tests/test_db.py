import db


def test_migrate_creates_career_schema(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "inbox.db")
    db.migrate()
    conn = db.connect()
    tables = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"opportunities", "companies", "run_log"} <= tables
    assert not {"travel_briefs", "accounts", "apartments"} & tables  # career-only cut
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(opportunities)")}
    assert {"dedupe_hash", "priority", "jd_text", "jd_fetched_at", "last_seen"} <= cols
    conn.close()


def test_insert_and_log_run(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "inbox.db")
    db.migrate()
    rid = db.insert("companies", {"name": "Solva", "name_key": "solva"})
    assert rid == 1
    db.log_run(skill="test", trigger="manual", status="ok", summary="s",
               started_at="2026-07-29T00:00:00")
    conn = db.connect()
    assert conn.execute("SELECT count(*) c FROM run_log").fetchone()["c"] == 1
    conn.close()
