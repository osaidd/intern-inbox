# tests/test_career_store.py
import db
from career_hunt import config as ch_config
from career_hunt.models import Job
from career_hunt.store import (get_or_create_company, insert_job, normalize_company,
                               recompute_priorities)

CFG = ch_config.load(ch_config.DEFAULT_PATH)


def _db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "life.db")
    db.migrate()
    return db.connect()


def _job(**kw):
    base = dict(company="Solva", role="AI Engineering Intern", url="https://x.co/1",
                source="github", location="New York, NY",
                jd_text="LLM agents, RAG, product ops.")
    base.update(kw)
    return Job(**base)


def test_normalize_company():
    assert normalize_company("Solva, Inc.") == "solva"
    assert normalize_company("  ACME LLC ") == "acme"
    assert normalize_company("Tessera") == "tessera"


def test_company_upsert_dedupes(tmp_path, monkeypatch):
    conn = _db(tmp_path, monkeypatch)
    a = get_or_create_company(conn, "Solva, Inc.")
    b = get_or_create_company(conn, "solva")
    assert a == b
    row = conn.execute("SELECT * FROM companies WHERE id=?", (a,)).fetchone()
    assert row["enrich_status"] == "pending"
    conn.close()


def test_insert_new_dup_excluded(tmp_path, monkeypatch):
    conn = _db(tmp_path, monkeypatch)
    outcome, pri = insert_job(conn, _job(), CFG)
    assert outcome == "new" and pri == "medium"   # unenriched + strong role → medium
    assert insert_job(conn, _job(), CFG) == ("dup", None)
    assert insert_job(conn, _job(location="Remote", url="https://x.co/2"), CFG) == ("excluded", None)
    row = conn.execute("SELECT * FROM opportunities").fetchone()
    assert row["priority"] == "medium" and row["company_id"] is not None
    assert row["work_mode"] in ("onsite", "hybrid", "unknown")
    conn.close()


def test_hints_make_it_high(tmp_path, monkeypatch):
    conn = _db(tmp_path, monkeypatch)
    get_or_create_company(conn, "Solva", hints={"stage": "seed", "headcount": 30,
                                                "enrich_source": "builtin"})
    outcome, pri = insert_job(conn, _job(), CFG)
    assert (outcome, pri) == ("new", "high")
    conn.close()


def test_company_upsert_inside_open_write_txn(tmp_path, monkeypatch):
    # Regression: get_or_create_company must INSERT through the caller's conn, not a
    # second connection, so it succeeds while the caller holds an open write txn.
    conn = _db(tmp_path, monkeypatch)
    conn.execute(
        "INSERT INTO opportunities (source, company, role, url, dedupe_hash, status) "
        "VALUES ('github', 'TxnCo', 'AI Eng', 'https://x.co/9', 'h9', 'new')")
    # NOT committed — open write transaction still held on conn.
    cid = get_or_create_company(conn, "TxnCo")
    assert isinstance(cid, int) and cid > 0
    conn.close()


def test_recompute_after_enrichment(tmp_path, monkeypatch):
    conn = _db(tmp_path, monkeypatch)
    insert_job(conn, _job(), CFG)                 # low (unenriched)
    cid = conn.execute("SELECT company_id FROM opportunities").fetchone()[0]
    conn.execute("UPDATE companies SET stage='seed', headcount=800, enrich_status='ok' "
                 "WHERE id=?", (cid,))
    changed = recompute_priorities(conn, CFG, cid)
    assert changed == 1
    row = conn.execute("SELECT status, priority FROM opportunities").fetchone()
    assert row["status"] == "dead"                # ≥100 people → auto-dead
    conn.close()
