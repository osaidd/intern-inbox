"""GitHub internship-list feed -> opportunities. Deterministic, no AI.
Run: uv run python -m feeds.github_intern_pull [--dry-run]
Writes: opportunities, companies, run_log."""
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import db  # noqa: E402
from career_hunt import config as ch_config  # noqa: E402
from career_hunt.emailer import maybe_send_digest  # noqa: E402
from career_hunt.store import insert_job  # noqa: E402
from career_hunt.sources import github_intern  # noqa: E402
from feeds.envfile import load_env  # noqa: E402


def main(dry_run: bool = False, trigger: str = "manual"):
    started = datetime.now().isoformat(timespec="seconds")
    load_env()
    cfg = ch_config.load()
    stats = {"found": 0, "new": 0, "dup": 0, "excluded": 0,
             "high": 0, "medium": 0, "low": 0}
    new_rows = []
    try:
        jobs, list_errors = github_intern.fetch(cfg)
        stats["found"], stats["list_errors"] = len(jobs), len(list_errors)
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
        finally:
            conn.close()
    except Exception as e:
        if not dry_run:
            db.log_run(skill="github-intern-pull", trigger=trigger, status="error",
                       summary=f"{type(e).__name__}: {e}"[:200], started_at=started,
                       finished_at=datetime.now().isoformat(timespec="seconds"),
                       metrics_json=json.dumps(stats))
        raise
    if not dry_run and new_rows:
        maybe_send_digest(cfg, new_rows, "github-intern-pull")
    summary = (f"found={stats['found']} new={stats['new']} dup={stats['dup']} "
               f"list_errors={stats.get('list_errors', 0)} "
               f"excluded={stats['excluded']} high={stats['high']} "
               f"med={stats['medium']} low={stats['low']}")
    if not dry_run:
        db.log_run(skill="github-intern-pull", trigger=trigger, status="ok",
                   summary=summary, started_at=started,
                   finished_at=datetime.now().isoformat(timespec="seconds"),
                   metrics_json=json.dumps(stats))
    print(summary)
    return stats


if __name__ == "__main__":
    main(dry_run="--dry-run" in sys.argv)
