import db
from career_hunt.models import Job
from feeds import ats_pull


def _job():
    return Job(company="Solva", role="AI Engineering Intern",
               url="https://jobs.ashbyhq.com/solva/aaaa-1111", source="ashby",
               location="New York, NY", posted_date="2026-07-20",
               jd_text="Ship LLM and RAG product features.",
               salary_text="$25 - $35 per hour")


def test_main_inserts_logs_and_dedupes(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "life.db")
    db.migrate()
    monkeypatch.setattr(ats_pull, "load_orgs",
                        lambda: (["solva", "deadorg"], []))
    monkeypatch.setattr(ats_pull.ats, "fetch",
                        lambda *a, **k: ([_job()], ["deadorg: HTTP 404"]))
    stats = ats_pull.main(trigger="manual")
    assert stats["found"] == 1 and stats["new"] == 1 and stats["org_errors"] == 1
    conn = db.connect()
    row = conn.execute(
        "SELECT source, company, jd_text, score, salary_text FROM opportunities").fetchone()
    log = conn.execute("SELECT skill, status, summary FROM run_log "
                       "ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    assert row["source"] == "ashby" and row["company"] == "Solva"
    assert "LLM and RAG" in row["jd_text"]          # jd_text lands at ingest, no hydration
    # ATS rows carry full JD at ingest, so they get the profile-fit score
    # immediately too — no jd_hydrate round-trip needed
    assert row["score"] is not None and row["score"] > 0
    assert row["salary_text"] == "$25 - $35 per hour"   # comp survives to the row
    assert log["skill"] == "ats-pull" and log["status"] == "ok"
    assert "new=1" in log["summary"] and "org_errors=1" in log["summary"]
    # second pass: same job → dup, nothing new
    stats2 = ats_pull.main(trigger="manual")
    assert stats2["new"] == 0 and stats2["dup"] == 1


def test_main_logs_error_row_on_total_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "life.db")
    db.migrate()
    monkeypatch.setattr(ats_pull, "load_orgs", lambda: (["solva"], []))

    def explode(*a, **k):
        raise RuntimeError("solva: HTTP 404")
    monkeypatch.setattr(ats_pull.ats, "fetch", explode)
    try:
        ats_pull.main(trigger="manual")
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected the total-failure to propagate")
    conn = db.connect()
    log = conn.execute("SELECT skill, status FROM run_log ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    assert log["skill"] == "ats-pull" and log["status"] == "error"


def test_main_drops_non_intern_rows_before_insert(tmp_path, monkeypatch):
    """Second enforcement layer of the internship red line: a row with NO intern
    signal (title, JD, or type) must never reach insert — but any single intern
    signal is enough, including an 'Intern' employment type alone."""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "life.db")
    db.migrate()
    monkeypatch.setattr(ats_pull, "load_orgs", lambda: (["solva"], []))
    no_signal = Job(company="Solva", role="AI Engineer",
                    url="https://jobs.ashbyhq.com/solva/zzzz-0000", source="ashby",
                    location="New York, NY", jd_text="llm agent product")
    type_only = Job(company="Solva", role="Software Engineer",
                    url="https://jobs.ashbyhq.com/solva/yyyy-0000", source="ashby",
                    location="New York, NY", jd_text="llm agent product",
                    employment_type="Intern")
    monkeypatch.setattr(ats_pull.ats, "fetch",
                        lambda *a, **k: ([_job(), type_only, no_signal], []))
    stats = ats_pull.main(trigger="manual")
    assert stats["found"] == 3 and stats["non_intern"] == 1 and stats["new"] == 2
    conn = db.connect()
    roles = sorted(r["role"] for r in conn.execute("SELECT role FROM opportunities"))
    log = conn.execute("SELECT summary FROM run_log ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    assert roles == ["AI Engineering Intern", "Software Engineer"]  # no-signal row never landed
    assert "non_intern=1" in log["summary"]


def test_main_migrates_a_fresh_db_itself(tmp_path, monkeypatch):
    """First use on a clone: nothing has run /setup, so the DB file has no schema.
    main() must apply migrations itself instead of tracebacking on 'no such table'."""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "inbox.db")   # deliberately NOT migrated
    monkeypatch.setattr(ats_pull, "load_orgs", lambda: (["solva"], []))
    monkeypatch.setattr(ats_pull.ats, "fetch", lambda *a, **k: ([_job()], []))
    stats = ats_pull.main(trigger="manual")
    assert stats["new"] == 1
    conn = db.connect()
    tables = {r["name"] for r in
              conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    log = conn.execute("SELECT skill, status FROM run_log ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    assert {"opportunities", "companies", "run_log", "schema_migrations"} <= tables
    assert log["skill"] == "ats-pull" and log["status"] == "ok"


def test_load_orgs_reads_sources_toml():
    ashby, greenhouse = ats_pull.load_orgs()
    assert isinstance(ashby, list) and isinstance(greenhouse, list)
