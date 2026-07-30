"""ATS board feed: Ashby + Greenhouse posting APIs -> opportunities. Deterministic, no AI.
Both APIs are free and keyless, with exact locations and full plain-text JDs —
jd_text lands at ingest, so these rows never need feeds/jd_hydrate.py.
HARD RED LINE: INTERNSHIPS ONLY. A row stays when ANY explicit intern signal
exists — intern/co-op in the title, internship wording in the JD, or an 'Intern'
employment type (the intern word supersedes a full-time type label); rows with no
intern signal anywhere are removed entirely. Gated in the parsers
(career_hunt.sources.ats.is_internship) and re-checked here before insert.
Org slugs live in [ats] (ashby_orgs / greenhouse_orgs) of the communal
config/sources.toml, plus anything your gitignored config/sources.local.toml adds.
Run: uv run python -m feeds.ats_pull [--dry-run]
Writes: opportunities, companies, run_log.

Follow-up (designed, not built — slug discovery over time): a small script or scan
step that, for live-row companies not yet in [ats], fetches the company website's
/careers (or /jobs) page, follows redirects and links looking for
jobs.ashbyhq.com/<slug>, boards.greenhouse.io/<slug>, or job-boards.greenhouse.io/<slug>,
confirms the slug with one probe of the matching API, and appends it to the [ats]
section of config/sources.local.toml. Politeness as here: sequential, ~1s spacing,
capped per run; never linkedin.com."""
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import db  # noqa: E402
from career_hunt import config as ch_config  # noqa: E402
from career_hunt.emailer import maybe_send_digest  # noqa: E402
from career_hunt.store import insert_job  # noqa: E402
from career_hunt.sources import ats  # noqa: E402
from feeds.config_load import load_sources  # noqa: E402
from feeds.envfile import load_env  # noqa: E402


def load_orgs() -> tuple:
    """Board slugs from the communal sources.toml merged with the local overlay."""
    section = load_sources()["ats"]
    return section["ashby_orgs"], section["greenhouse_orgs"]


def main(dry_run: bool = False, trigger: str = "manual"):
    started = datetime.now().isoformat(timespec="seconds")
    db.migrate()      # first run on a clone may predate /setup; no-op when current
    load_env()
    cfg = ch_config.load()
    ashby_orgs, greenhouse_orgs = load_orgs()
    stats = {"orgs": len(ashby_orgs) + len(greenhouse_orgs), "found": 0, "new": 0,
             "dup": 0, "excluded": 0, "non_intern": 0, "org_errors": 0,
             "high": 0, "medium": 0, "low": 0}
    new_rows = []
    try:
        jobs, errors = ats.fetch(ashby_orgs, greenhouse_orgs, cfg)
        stats["found"], stats["org_errors"] = len(jobs), len(errors)
        # red-line re-check: the parsers already gate, but nothing non-intern may
        # reach insert even through a parser bug
        interns = [j for j in jobs
                   if ats.is_internship(j.role, j.jd_text, j.employment_type)]
        stats["non_intern"] = len(jobs) - len(interns)
        jobs = interns
        # ATS rows carry the full JD at ingest, so the profile-fit score lands
        # immediately (jobspy_pull pattern) — no jd_hydrate round-trip.
        from feeds.jobspy_pull import load_config, score_job
        legacy_cfg = load_config()
        conn = db.connect()
        try:
            for j in jobs:
                outcome, pri = insert_job(conn, j, cfg, dry_run=dry_run)
                stats[outcome if outcome != "new" else pri] = \
                    stats.get(outcome if outcome != "new" else pri, 0) + 1
                if outcome == "new":
                    stats["new"] += 1
                    new_rows.append({"company": j.company, "role": j.role,
                                     "url": j.url, "priority": pri,
                                     "source": j.source})
                if outcome in ("new", "dup") and not dry_run:
                    # score lands at ingest; re-sightings self-heal rows that
                    # predate scoring (score is only ever backfilled, never moved)
                    s = score_job(j.role, j.jd_text, j.posted_date, legacy_cfg)
                    if s is not None:
                        conn.execute(
                            "UPDATE opportunities SET score=? "
                            "WHERE dedupe_hash=? AND score IS NULL",
                            (s, j.dedupe_hash()))
                        conn.commit()
        finally:
            conn.close()
    except Exception as e:
        if not dry_run:
            db.log_run(skill="ats-pull", trigger=trigger, status="error",
                       summary=f"{type(e).__name__}: {e}"[:200], started_at=started,
                       finished_at=datetime.now().isoformat(timespec="seconds"),
                       metrics_json=json.dumps(stats))
        raise
    if not dry_run and new_rows:
        maybe_send_digest(cfg, new_rows, "ats-pull")
    summary = (f"orgs={stats['orgs']} found={stats['found']} new={stats['new']} "
               f"dup={stats['dup']} excluded={stats['excluded']} "
               f"non_intern={stats['non_intern']} org_errors={stats['org_errors']} "
               f"high={stats['high']} med={stats['medium']} low={stats['low']}")
    if not dry_run:
        db.log_run(skill="ats-pull", trigger=trigger, status="ok",
                   summary=summary, started_at=started,
                   finished_at=datetime.now().isoformat(timespec="seconds"),
                   metrics_json=json.dumps(stats))
    print(summary)
    return stats


if __name__ == "__main__":
    main(dry_run="--dry-run" in sys.argv)
