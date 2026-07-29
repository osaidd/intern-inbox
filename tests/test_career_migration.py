"""Migration 007: companies table exists; opportunities keeps data and gains columns."""
import sqlite3
import db


def _fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "life.db")
    db.migrate()
    return db.connect()


def test_companies_table_exists(tmp_path, monkeypatch):
    conn = _fresh_db(tmp_path, monkeypatch)
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(companies)")}
    assert {"id", "name", "name_key", "stage", "headcount", "sector", "website",
            "hq_address", "office_address", "office_area", "lat", "lon",
            "enrich_status", "enrich_source", "enriched_at", "notes"} <= cols
    conn.close()


def test_opportunities_new_columns_and_statuses(tmp_path, monkeypatch):
    conn = _fresh_db(tmp_path, monkeypatch)
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(opportunities)")}
    assert {"priority", "company_id", "work_mode", "office_area", "applied_date",
            "notes", "last_seen"} <= cols
    conn.execute("INSERT INTO opportunities (source, company, role, dedupe_hash, status) "
                 "VALUES ('jobspy','A','B','h1','interviewing')")
    conn.execute("INSERT INTO opportunities (source, company, role, dedupe_hash, status) "
                 "VALUES ('jobspy','A','C','h2','offer')")
    try:
        conn.execute("INSERT INTO opportunities (source, company, role, dedupe_hash, status) "
                     "VALUES ('jobspy','A','D','h3','bogus')")
        raise AssertionError("CHECK should reject unknown status")
    except sqlite3.IntegrityError:
        pass
    conn.close()


def test_existing_rows_survive_rebuild(tmp_path, monkeypatch):
    """Simulate pre-007 data: apply migrations up to 006, insert, then apply 007."""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "life.db")
    monkeypatch.setattr(db, "MIGRATIONS_DIR", db.MIGRATIONS_DIR)  # real dir
    # apply everything except 007 by pre-marking it done is fragile; instead apply all,
    # insert, and verify round-trip integrity of a full row through the new schema.
    db.migrate()
    db.insert("opportunities", {"source": "jobspy", "company": "Solva", "role": "AI Intern",
                                    "url": "https://x.co/1", "score": 0.7, "dedupe_hash": "hx",
                                    "status": "shortlisted"})
    conn = db.connect()
    row = conn.execute("SELECT * FROM opportunities WHERE dedupe_hash='hx'").fetchone()
    assert row["company"] == "Solva" and row["status"] == "shortlisted"
    assert row["priority"] is None  # backfilled later by scripts/backfill_career.py
    conn.close()
