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


def test_007_stage_mail_tables(tmp_path, monkeypatch):
    conn = _fresh_db(tmp_path, monkeypatch)
    for table, need in {
        "stage_events": {"opportunity_id", "from_status", "to_status", "occurred_at",
                         "source", "note", "suggestion_id"},
        "contact_events": {"company_id", "opportunity_id", "direction", "channel",
                           "occurred_at", "subject", "snippet", "message_id",
                           "created_by", "created_at"},
        "email_messages": {"dedupe_key", "gm_msgid", "message_id", "folder",
                           "from_addr", "to_addrs", "subject", "sent_at",
                           "matched_company_id", "classification", "processed_at"},
        "suggestions": {"kind", "opportunity_id", "company_id", "email_message_id",
                        "evidence", "status", "created_at", "resolved_at"},
        "company_domains": {"company_id", "domain", "source", "created_at"},
    }.items():
        cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        assert need <= cols, table
    conn.close()


def test_008_next_action_columns(tmp_path, monkeypatch):
    conn = _fresh_db(tmp_path, monkeypatch)
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(opportunities)")}
    assert {"next_action_date", "next_action_note"} <= cols
    conn.close()


def test_007_checks_and_uniques(tmp_path, monkeypatch):
    conn = _fresh_db(tmp_path, monkeypatch)
    conn.execute("INSERT INTO opportunities (source, company, role, dedupe_hash, status) "
                 "VALUES ('jobspy','A','B','h1','new')")
    bad = [
        ("INSERT INTO stage_events (opportunity_id, to_status, occurred_at, source) "
         "VALUES (1,'applied','2026-09-01','robot')"),                    # bad source
        ("INSERT INTO suggestions (kind, opportunity_id, created_at) "
         "VALUES ('set_dead',1,'2026-09-01')"),                           # bad kind
        ("INSERT INTO contact_events (opportunity_id, direction, channel, occurred_at, "
         "created_by, created_at) VALUES (1,'sideways','email','2026-09-01','user','x')"),
        ("INSERT INTO contact_events (direction, channel, occurred_at, created_by, "
         "created_at) VALUES ('out','email','2026-09-01','user','x')"),   # both ids NULL
    ]
    for sql in bad:
        try:
            conn.execute(sql)
            raise AssertionError(f"CHECK should reject: {sql}")
        except sqlite3.IntegrityError:
            pass
    conn.execute("INSERT INTO email_messages (dedupe_key, folder, processed_at) "
                 "VALUES ('k1','inbox','x')")
    try:
        conn.execute("INSERT INTO email_messages (dedupe_key, folder, processed_at) "
                     "VALUES ('k1','sent','x')")
        raise AssertionError("dedupe_key must be UNIQUE")
    except sqlite3.IntegrityError:
        pass
    conn.execute("INSERT INTO contact_events (opportunity_id, direction, channel, "
                 "occurred_at, message_id, created_by, created_at) "
                 "VALUES (1,'in','email','2026-09-01','m1','mail-scan','x')")
    try:
        conn.execute("INSERT INTO contact_events (opportunity_id, direction, channel, "
                     "occurred_at, message_id, created_by, created_at) "
                     "VALUES (1,'in','email','2026-09-01','m1','mail-scan','x')")
        raise AssertionError("contact message_id must be UNIQUE when present")
    except sqlite3.IntegrityError:
        pass
    # NULL message_id rows (manual logs) are exempt from the partial unique index
    for _ in range(2):
        conn.execute("INSERT INTO contact_events (opportunity_id, direction, channel, "
                     "occurred_at, created_by, created_at) "
                     "VALUES (1,'out','manual','2026-09-01','user','x')")
    conn.close()


def test_007_backfill_seeds_triaged_rows(tmp_path, monkeypatch):
    """Rows that predate 007 get one anchor stage_event; 'new' rows get none and
    applied rows anchor to their real applied_date."""
    import shutil
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "life.db")
    real_dir = db.MIGRATIONS_DIR
    staged = tmp_path / "migrations"
    staged.mkdir()
    for f in sorted(real_dir.glob("*.sql")):
        if f.name < "007":
            shutil.copy(f, staged / f.name)
    monkeypatch.setattr(db, "MIGRATIONS_DIR", staged)
    db.migrate()                              # pre-007 schema
    conn = db.connect()
    conn.execute("INSERT INTO opportunities (source, company, role, dedupe_hash, status, "
                 "applied_date, discovered_date) "
                 "VALUES ('jobspy','A','B','h1','applied','2026-08-15','2026-08-01')")
    conn.execute("INSERT INTO opportunities (source, company, role, dedupe_hash, status, "
                 "discovered_date) VALUES ('jobspy','A','C','h2','interviewing','2026-08-02')")
    conn.execute("INSERT INTO opportunities (source, company, role, dedupe_hash, status) "
                 "VALUES ('jobspy','A','D','h3','new')")
    conn.commit()
    conn.close()
    for f in sorted(real_dir.glob("*.sql")):
        if not (staged / f.name).exists():
            shutil.copy(f, staged / f.name)
    db.migrate()                              # 007 applies + backfills
    conn = db.connect()
    events = conn.execute(
        "SELECT o.dedupe_hash AS h, e.from_status, e.to_status, e.occurred_at, e.source "
        "FROM stage_events e JOIN opportunities o ON o.id = e.opportunity_id "
        "ORDER BY o.dedupe_hash").fetchall()
    conn.close()
    assert [(e["h"], e["from_status"], e["to_status"], e["occurred_at"], e["source"])
            for e in events] == [
        ("h1", None, "applied", "2026-08-15", "backfill"),
        ("h2", None, "interviewing", "2026-08-02", "backfill"),
    ]


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
