"""JobSpy sourcing feed: Indeed + Google Jobs -> opportunities table. Deterministic, no AI."""
import json
import sys
import tomllib
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import db
from career_hunt import config as ch_config
from career_hunt.config import EXAMPLE_PATH, USER_PATH
from career_hunt.models import Job, dedupe_hash  # dedupe_hash re-exported for test back-compat
from career_hunt.store import insert_job
from feeds.config_load import load_sources


def _clean(v):
    """None-ify pandas NaN values from scraped rows; pass everything else through."""
    if v is None or (isinstance(v, float) and v != v):
        return None
    return v


def load_config() -> dict:
    """Raw-dict config for the legacy profile-fit score: the merged sources
    (communal + local overlay) plus the career config's own tables — [scoring] among
    them. Personal career.toml wins; a fresh clone falls back to the example."""
    cfg = load_sources()
    path = USER_PATH if USER_PATH.exists() else EXAMPLE_PATH
    with open(path, "rb") as f:
        cfg.update(tomllib.load(f))
    return cfg


def recency_score(posted_date) -> float:
    if not posted_date:
        return 0.3
    try:
        days = (date.today() - date.fromisoformat(str(posted_date)[:10])).days
    except ValueError:
        return 0.3
    return 1.0 if days <= 7 else 0.6 if days <= 30 else 0.2


def score_job(title: str, description, posted_date, cfg: dict):
    """Profile-fit score 0..1; None = hard-excluded by title keyword."""
    sc = cfg["scoring"]
    title_l = (title or "").lower()
    if any(k in title_l for k in sc["exclude_keywords"]):
        return None
    text = f"{title_l}\n{(description or '').lower()}"
    kws = sc["profile_keywords"]
    keyword_match = sum(1 for k in kws if k in text) / len(kws)
    if any(t in title_l for t in ("intern", "internship", "co-op", "coop")):
        intern_signal = 1.0
    elif any(t in title_l for t in ("junior", "graduate", "entry")):
        intern_signal = 0.4
    else:
        intern_signal = 0.0
    stage_fit = 0.5  # boards carry no company-stage data; skill's NOC pass refines
    w = sc["weights"]
    raw = (w["keyword_match"] * keyword_match + w["stage_fit"] * stage_fit
           + w["intern_signal"] * intern_signal + w["recency"] * recency_score(posted_date))
    # Wishlist boost: dream-role titles ([scoring].target_titles, substring,
    # case-insensitive) get x1.25 capped at 1.0 so they outrank generic matches.
    if any(t.lower() in title_l for t in sc.get("target_titles", [])):
        raw = min(raw * 1.25, 1.0)
    return round(raw, 4)


def fetch_jobs(cfg: dict) -> list:
    from jobspy import scrape_jobs  # heavy import, keep local
    src = cfg["jobspy"]
    jobs = []
    for q in src["role_queries"]:
        df = scrape_jobs(site_name=src["sites"], search_term=q, location=src["location"],
                         country_indeed=src["country_indeed"],
                         results_wanted=src.get("results_per_query", 25), hours_old=24 * 30)
        for _, r in df.iterrows():
            desc = _clean(r.get("description"))
            pd_raw = _clean(r.get("date_posted"))
            jobs.append({
                "company": _clean(r.get("company")), "role": _clean(r.get("title")),
                "url": _clean(r.get("job_url")), "location": _clean(r.get("location")),
                "posted_date": (str(pd_raw) or None) if pd_raw is not None else None,
                "jd_text": (str(desc)[:20000] if desc is not None else None),
            })
    return jobs


def main(dry_run: bool = False, trigger: str = "manual"):
    started = datetime.now().isoformat(timespec="seconds")
    cfg = load_config()
    found = new = skipped = excluded = malformed = 0
    try:
        jobs = fetch_jobs(cfg)
        found = len(jobs)
        ch_cfg = ch_config.load()
        conn = db.connect()
        try:
            for j in jobs:
                j = {k: _clean(v) for k, v in j.items()}
                company, role = j.get("company"), j.get("role")
                if not (isinstance(company, str) and company.strip()) \
                        or not (isinstance(role, str) and role.strip()):
                    malformed += 1
                    continue
                job = Job(company=company, role=role, url=j.get("url"), source="jobspy",
                          location=j.get("location"), posted_date=j.get("posted_date"),
                          jd_text=j.get("jd_text"))
                outcome, pri = insert_job(conn, job, ch_cfg, dry_run=dry_run)
                if outcome == "dup":
                    skipped += 1
                    continue
                if outcome == "excluded":
                    excluded += 1
                    continue
                new += 1
                s = score_job(role, j.get("jd_text"), j.get("posted_date"), cfg)
                if s is not None and not dry_run:
                    conn.execute("UPDATE opportunities SET score=? WHERE dedupe_hash=?",
                                 (s, job.dedupe_hash()))
                    conn.commit()
        finally:
            conn.close()
    except Exception as e:
        if not dry_run:
            db.log_run(skill="jobspy-pull", trigger=trigger, status="error",
                       summary=f"{type(e).__name__}: {e}"[:200],
                       started_at=started,
                       finished_at=datetime.now().isoformat(timespec="seconds"),
                       metrics_json=json.dumps({"found": found, "new": new,
                                                "skipped_existing": skipped,
                                                "excluded": excluded, "malformed": malformed}))
        raise
    summary = f"{new} new / {found} found"
    if not dry_run:
        db.log_run(skill="jobspy-pull", trigger=trigger, status="ok", summary=summary,
                   started_at=started, finished_at=datetime.now().isoformat(timespec="seconds"),
                   metrics_json=json.dumps({"found": found, "new": new,
                                            "skipped_existing": skipped,
                                            "excluded": excluded, "malformed": malformed}))
    print(f"found={found} new={new} skipped_existing={skipped} excluded={excluded} malformed={malformed}")


if __name__ == "__main__":
    main(dry_run="--dry-run" in sys.argv)
