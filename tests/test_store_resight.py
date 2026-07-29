import db
from career_hunt import config as ch_config
from career_hunt.models import Job
from career_hunt.store import insert_job

CFG = ch_config.load(ch_config.DEFAULT_PATH)


def _db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "life.db")
    db.migrate()
    return db.connect()


def _job(**kw):
    base = dict(company="Solva", role="AI Engineering Intern", url="https://x.co/1",
                source="github", location="New York, NY", jd_text="LLM agents, RAG.")
    base.update(kw)
    return Job(**base)


def test_resight_bumps_last_seen_and_backfills(tmp_path, monkeypatch):
    conn = _db(tmp_path, monkeypatch)
    insert_job(conn, _job(jd_text=None, posted_date=None), CFG)
    conn.execute("UPDATE opportunities SET last_seen='2026-01-01', status='shortlisted',"
                 " notes='mine'")
    conn.commit()
    out = insert_job(conn, _job(jd_text="Full JD text now", posted_date="2026-07-01"), CFG)
    assert out == ("dup", None)
    row = conn.execute("SELECT * FROM opportunities").fetchone()
    assert row["last_seen"] != "2026-01-01"          # bumped to today
    assert row["jd_text"] == "Full JD text now"      # backfilled (was NULL)
    assert row["posted_date"] == "2026-07-01"
    assert row["status"] == "shortlisted" and row["notes"] == "mine"  # untouched
    conn.close()


def test_resight_never_overwrites_existing(tmp_path, monkeypatch):
    conn = _db(tmp_path, monkeypatch)
    insert_job(conn, _job(), CFG)
    insert_job(conn, _job(jd_text="different text", url="https://x.co/1"), CFG)
    row = conn.execute("SELECT jd_text FROM opportunities").fetchone()
    assert row["jd_text"] == "LLM agents, RAG."      # existing value preserved
    conn.close()
