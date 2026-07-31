"""Migration 003: companies table exists; opportunities keeps data and gains columns."""
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
    """The overhaul migration DROPs and rebuilds opportunities. Stage a genuinely
    pre-rebuild row: apply only the early migrations, insert through the OLD
    schema, then apply the rest and assert the row survived with new columns."""
    import shutil
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "life.db")
    real_dir = db.MIGRATIONS_DIR
    staged = tmp_path / "migrations"
    staged.mkdir()
    for name in ("001_runlog.sql", "002_career.sql",):
        shutil.copy(real_dir / name, staged / name)
    monkeypatch.setattr(db, "MIGRATIONS_DIR", staged)
    db.migrate()                              # old schema only
    conn = db.connect()
    conn.execute("INSERT INTO opportunities (source, company, role, url, score, "
                 "dedupe_hash, status) VALUES ('jobspy','Solva','AI Intern',"
                 "'https://x.co/1',0.7,'hx','shortlisted')")
    conn.commit()
    conn.close()
    for f in sorted(real_dir.glob("*.sql")):     # now the rest, incl. rebuild
        if not (staged / f.name).exists():
            shutil.copy(f, staged / f.name)
    db.migrate()
    conn = db.connect()
    row = conn.execute("SELECT * FROM opportunities WHERE dedupe_hash='hx'").fetchone()
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(opportunities)")}
    conn.close()
    assert row["company"] == "Solva" and row["status"] == "shortlisted"
    assert row["score"] == 0.7                   # data round-tripped the rebuild
    assert {"priority", "last_seen", "salary_text"} <= cols   # new columns arrived
