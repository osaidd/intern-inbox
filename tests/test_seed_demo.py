import pytest

import db
from automation import seed_demo


@pytest.fixture()
def fresh(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "demo.db")
    db.migrate()


def test_seeds_fifteen_new_rows(fresh):
    n = seed_demo.seed()
    conn = db.connect_ro()
    rows = conn.execute("SELECT status, priority, company FROM opportunities").fetchall()
    conn.close()
    assert n == len(rows) == 15
    assert {r["status"] for r in rows} == {"new"}
    assert any(r["priority"] == "high" for r in rows)


def test_refuses_nonempty_db(fresh):
    seed_demo.seed()
    with pytest.raises(SystemExit):
        seed_demo.seed()
