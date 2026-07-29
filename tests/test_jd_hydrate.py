"""JD hydration: fetch gating, linkedin skip, retry stamp, score+text write."""
import db
from career_hunt import config as ch_config
from career_hunt.config import user_agent
from feeds import jd_hydrate

PAGE = ("<html><head><style>x{}</style></head><body><h1>AI Engineering Intern</h1>"
        "<p>" + "Build LLM agents with RAG for product operations. " * 30 + "</p>"
        "<script>tracking()</script></body></html>")


def _db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "life.db")
    db.migrate()
    return db


def _row(hash_, **kw):
    base = {"source": "jobspy", "company": "Solva", "role": "AI Engineering Intern",
            "url": "https://boards.example.com/j/1", "location": "New York, NY",
            "dedupe_hash": hash_, "status": "new", "priority": "high"}
    base.update(kw)
    return base


def fake_opener(req, timeout):
    class R:
        def read(self):
            return PAGE.encode()
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
    assert timeout == 15
    return R()


def test_extract_text_drops_script_style():
    text = jd_hydrate.extract_text(PAGE)
    assert "tracking()" not in text and "color-scheme" not in text.lower()
    assert "LLM agents" in text


def test_hydrates_scores_and_stamps(tmp_path, monkeypatch):
    db = _db(tmp_path, monkeypatch)
    db.insert("opportunities", _row("h1"))
    db.insert("opportunities", _row("h2", url="https://www.linkedin.com/jobs/view/1"))
    db.insert("opportunities", _row("h3", jd_fetched_at="2099-01-01",
                                    url="https://boards.example.com/j/3"))
    stats = jd_hydrate.main(_opener=fake_opener, _sleep=lambda s: None)
    assert stats["tried"] == 1 and stats["hydrated"] == 1        # h2 linkedin-skipped, h3 stamped
    conn = db.connect()
    r1 = conn.execute("SELECT * FROM opportunities WHERE dedupe_hash='h1'").fetchone()
    assert r1["jd_text"] and "LLM agents" in r1["jd_text"]
    assert r1["jd_fetched_at"] and r1["score"] is not None
    r2 = conn.execute("SELECT jd_text, jd_fetched_at FROM opportunities "
                      "WHERE dedupe_hash='h2'").fetchone()
    assert r2["jd_text"] is None and r2["jd_fetched_at"] is None  # linkedin never touched
    run = conn.execute("SELECT skill, status FROM run_log ORDER BY id DESC LIMIT 1").fetchone()
    assert run["skill"] == "jd-hydrate" and run["status"] == "ok"
    conn.close()


def test_outbound_fetch_sends_the_config_user_agent(tmp_path, monkeypatch):
    """The UA is built from the running user's own config — never a hardcoded
    personal contact address baked into the source."""
    db = _db(tmp_path, monkeypatch)
    db.insert("opportunities", _row("h1"))
    seen = {}

    def capturing_opener(req, timeout):
        seen["ua"] = req.get_header("User-agent")
        return fake_opener(req, timeout)

    jd_hydrate.main(_opener=capturing_opener, _sleep=lambda s: None)
    assert seen["ua"] == user_agent(ch_config.load())["User-Agent"]
    assert "@" not in jd_hydrate.DEFAULT_UA["User-Agent"]   # fallback carries no address


def test_dead_page_stamps_without_text(tmp_path, monkeypatch):
    db = _db(tmp_path, monkeypatch)
    db.insert("opportunities", _row("h1"))
    def dead_opener(req, timeout):
        raise OSError("connection refused")
    stats = jd_hydrate.main(_opener=dead_opener, _sleep=lambda s: None)
    assert stats["thin_or_dead"] == 1 and stats["hydrated"] == 0
    conn = db.connect()
    r = conn.execute("SELECT jd_text, jd_fetched_at FROM opportunities").fetchone()
    assert r["jd_text"] is None and r["jd_fetched_at"]            # stamped: no daily retry
    conn.close()
