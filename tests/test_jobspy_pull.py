import sqlite3

import pytest

import db
from feeds import jobspy_pull as jp


CFG = {
    "scoring": {
        "profile_keywords": ["data", "analytics", "fintech"],
        "exclude_keywords": ["senior", "staff"],
        "weights": {"keyword_match": 0.4, "stage_fit": 0.2, "intern_signal": 0.3, "recency": 0.1},
    },
}


@pytest.fixture   # not named `db` — that would shadow the `db` module imported above
def inbox_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "life.db")
    db.migrate()
    return db


def test_dedupe_hash_normalizes():
    a = jp.dedupe_hash("Acme  Inc", "Data Intern", "https://a.co/j/1/")
    b = jp.dedupe_hash("acme inc", "data intern", "https://a.co/j/1")
    assert a == b
    assert jp.dedupe_hash("Acme", "Data Intern", None) != a


def test_dedupe_hash_tolerates_non_strings():
    nan = float("nan")
    assert jp.dedupe_hash(nan, nan, nan) == jp.dedupe_hash(None, None, None)
    assert jp.dedupe_hash("Acme", "Data Intern", nan) == jp.dedupe_hash("Acme", "Data Intern", None)


def test_score_excludes_senior_titles():
    assert jp.score_job("Senior Data Analyst", "data data", "2026-07-01", CFG) is None


def test_score_rewards_intern_and_keywords():
    hi = jp.score_job("Data Analyst Intern", "analytics fintech data role", "2026-07-01", CFG)
    lo = jp.score_job("Office Manager", "answer phones", "2025-01-01", CFG)
    assert hi is not None and lo is not None and hi > lo
    assert 0.0 <= lo <= hi <= 1.0


def test_recency_score_bands():
    from datetime import date, timedelta
    today = date.today()
    assert jp.recency_score(str(today)) == 1.0
    assert jp.recency_score(str(today - timedelta(days=20))) == 0.6
    assert jp.recency_score(str(today - timedelta(days=90))) == 0.2
    assert jp.recency_score(None) == 0.3


def test_main_inserts_once_and_logs(inbox_db, monkeypatch):
    fake = [
        {"company": "Acme", "role": "Data Analyst Intern", "url": "https://a.co/1",
         "location": "New York, NY", "posted_date": "2026-07-01", "jd_text": "analytics fintech"},
        {"company": "BigCo", "role": "Senior Data Analyst", "url": "https://b.co/2",
         "location": "New York, NY", "posted_date": "2026-07-01", "jd_text": "data"},
    ]
    monkeypatch.setattr(jp, "fetch_jobs", lambda cfg: fake)
    jp.main()
    jp.main()  # second run: everything deduped
    conn = inbox_db.connect()
    assert conn.execute("SELECT count(*) FROM opportunities").fetchone()[0] == 1  # senior excluded
    row = conn.execute("SELECT * FROM opportunities").fetchone()
    assert row["company"] == "Acme" and row["jd_text"] == "analytics fintech"
    assert row["score"] is not None
    runs = conn.execute("SELECT count(*) FROM run_log WHERE skill='jobspy-pull'").fetchone()[0]
    assert runs == 2


def test_main_logs_error_row_on_fetch_failure(inbox_db, monkeypatch):
    def boom(cfg):
        raise RuntimeError("rate limited")
    monkeypatch.setattr(jp, "fetch_jobs", boom)
    with pytest.raises(RuntimeError):
        jp.main()
    row = inbox_db.connect().execute(
        "SELECT status, summary FROM run_log WHERE skill='jobspy-pull'").fetchone()
    assert row["status"] == "error"
    assert "rate limited" in row["summary"]


def test_main_counts_malformed_rows(inbox_db, monkeypatch, capsys):
    fake = [
        {"company": None, "role": "X", "url": "u"},
        {"company": "Acme", "role": "Data Analyst Intern", "url": "https://a.co/9",
         "location": "New York, NY", "posted_date": "2026-07-01", "jd_text": "data analytics"},
    ]
    monkeypatch.setattr(jp, "fetch_jobs", lambda cfg: fake)
    jp.main()
    out = capsys.readouterr().out
    assert "malformed=1" in out and "new=1" in out


def test_nan_company_counts_malformed_not_crash(inbox_db, monkeypatch, capsys):
    fake = [
        {"company": float("nan"), "role": "Data Intern", "url": "https://n.co/1",
         "location": "NYC", "posted_date": "2026-07-01", "jd_text": "data"},
        {"company": "Acme", "role": "Data Analyst Intern", "url": "https://a.co/7",
         "location": "New York, NY", "posted_date": "2026-07-01", "jd_text": float("nan")},
    ]
    monkeypatch.setattr(jp, "fetch_jobs", lambda cfg: fake)
    jp.main()
    out = capsys.readouterr().out
    assert "malformed=1" in out and "new=1" in out
    row = inbox_db.connect().execute("SELECT jd_text FROM opportunities WHERE company='Acme'").fetchone()
    assert row["jd_text"] is None


def test_non_string_or_empty_company_counts_malformed(inbox_db, monkeypatch, capsys):
    fake = [
        {"company": 12.5, "role": "Data Intern", "url": "https://n.co/2"},
        {"company": "", "role": "Data Intern", "url": "https://n.co/3"},
        {"company": "Acme", "role": "", "url": "https://n.co/4"},
    ]
    monkeypatch.setattr(jp, "fetch_jobs", lambda cfg: fake)
    jp.main()
    assert "malformed=3" in capsys.readouterr().out


def test_clean_helper():
    assert jp._clean(float("nan")) is None
    assert jp._clean(None) is None
    assert jp._clean("x") == "x"
    assert jp._clean(0.5) == 0.5


def test_non_nyc_and_remote_rows_excluded(inbox_db, monkeypatch, capsys):
    # Location/remote gating now lives in the shared career_hunt.score.matches path;
    # the local excluded_location counter is gone (folded into `excluded`).
    fake = [
        {"company": "A", "role": "Data Intern", "url": "https://a.co/1", "location": "Remote",
         "posted_date": "2026-07-01", "jd_text": "data"},
        {"company": "B", "role": "Data Intern", "url": "https://b.co/2", "location": "Albany, NY",
         "posted_date": "2026-07-01", "jd_text": "data"},
        {"company": "C", "role": "Data Analyst Intern", "url": "https://c.co/3", "location": "Brooklyn, NY",
         "posted_date": "2026-07-01", "jd_text": "data analytics"},
        {"company": "D", "role": "Data Intern", "url": "https://d.co/4", "location": None,
         "posted_date": "2026-07-01", "jd_text": "data"},
    ]
    monkeypatch.setattr(jp, "fetch_jobs", lambda cfg: fake)
    jp.main()
    out = capsys.readouterr().out
    assert "excluded=3" in out and "new=1" in out
    rows = inbox_db.connect().execute("SELECT company FROM opportunities").fetchall()
    assert [r["company"] for r in rows] == ["C"]


def test_empty_string_company_is_malformed(inbox_db, monkeypatch, capsys):
    fake = [{"company": "  ", "role": "Data Intern", "url": "https://e.co/5",
             "location": "New York, NY", "posted_date": "2026-07-01", "jd_text": "data"}]
    monkeypatch.setattr(jp, "fetch_jobs", lambda cfg: fake)
    jp.main()
    assert "malformed=1" in capsys.readouterr().out


# NJ-metro location and startup-size gate tests moved to tests/test_career_score.py
# (Build: career-hunt overhaul — the gates live in career_hunt.score now).

def test_target_title_boost_multiplies_and_caps():
    from datetime import date
    today = str(date.today())
    boosted_cfg = {"scoring": {**CFG["scoring"],
                               "target_titles": ["founders associate", "data analyst intern"]}}
    base = jp.score_job("Founders Associate", "data analytics fintech", today, CFG)
    boosted = jp.score_job("Founders Associate", "data analytics fintech", today, boosted_cfg)
    assert boosted == round(min(base * 1.25, 1.0), 4) and boosted > base
    # already-strong title match hits the 1.0 cap (raw 0.9 * 1.25 = 1.125 -> 1.0)
    assert jp.score_job("Data Analyst Intern", "data analytics fintech",
                        today, boosted_cfg) == 1.0
    # non-target titles are untouched
    assert jp.score_job("Office Manager", "data", today, boosted_cfg) == \
        jp.score_job("Office Manager", "data", today, CFG)


def test_main_inserts_with_priority(tmp_path, monkeypatch):
    import db
    import feeds.jobspy_pull as jp
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "life.db")
    db.migrate()
    monkeypatch.setattr(jp, "fetch_jobs", lambda cfg: [
        {"company": "Solva", "role": "AI Engineering Intern",
         "url": "https://x.co/1", "location": "New York, NY",
         "posted_date": None, "jd_text": "LLM agents and RAG."},
        {"company": "BigCo", "role": "AI Intern", "url": "https://x.co/2",
         "location": "Remote", "posted_date": None, "jd_text": "remote first"},
    ])
    jp.main()
    conn = db.connect()
    rows = conn.execute("SELECT company, priority, company_id FROM opportunities").fetchall()
    conn.close()
    assert len(rows) == 1 and rows[0]["company"] == "Solva"
    assert rows[0]["priority"] == "medium" and rows[0]["company_id"] is not None


def test_main_excludes_big_companies_and_red_flag_jds(inbox_db, monkeypatch, capsys):
    fake = [
        {"company": "Google", "role": "Data Analyst Intern", "url": "https://g.co/1",
         "location": "New York, NY", "posted_date": "2026-07-01", "jd_text": "data"},
        {"company": "MysteryCo", "role": "Data Analyst Intern", "url": "https://m.co/2",
         "location": "New York, NY", "posted_date": "2026-07-01",
         "jd_text": "We are publicly traded with global offices"},
        {"company": "Ramp", "role": "Data Analyst Intern", "url": "https://r.co/3",
         "location": "New York, NY", "posted_date": "2026-07-01",
         "jd_text": "seed-stage data team"},
    ]
    monkeypatch.setattr(jp, "fetch_jobs", lambda cfg: fake)
    jp.main()
    out = capsys.readouterr().out
    assert "excluded=2" in out and "new=1" in out
    rows = inbox_db.connect().execute("SELECT company FROM opportunities").fetchall()
    assert [r["company"] for r in rows] == ["Ramp"]
