# intern-inbox — conventions

NYC/NJ **internships only** — both gates are hard-coded in `career_hunt/score.py`.
ALL DB access via `db.py` (`uv run python -c "import db; db.migrate()"` applies migrations).
Every skill/feed run writes ONE `run_log` row via `db.log_run()` — non-optional.
Secrets only in `config/.env` (gitignored). Personal config is gitignored; tracked
`*.example` files are templates — never write personal values into tracked files.
Never scrape linkedin.com — job-alert emails are the only LinkedIn channel.
Python via `uv` only. Tests: `uv run pytest`.

## Write contract
| Writer | Writes |
|---|---|
| feeds/ats_pull.py (internships-only, Ashby+Greenhouse; skill `ats-pull`) | opportunities, companies, run_log |
| feeds/linkedin_mail_pull.py (LinkedIn/Built In/Wellfound alert mail; skill `linkedin-mail-pull`) | opportunities, companies, run_log |
| feeds/github_intern_pull.py | opportunities, companies, run_log |
| feeds/jobspy_pull.py | opportunities, companies, run_log |
| feeds/jd_hydrate.py | opportunities (jd_text/score/priority/jd_fetched_at), run_log |
| opportunity-scan | vault/outputs/career/, opportunities, companies, run_log |
| add-opportunity | opportunities, companies, run_log |
| pipeline-review | opportunities.status (+applied_date), run_log |
| skills-gap | vault/outputs/career/, profile/ (user-approved edits only), run_log |
| setup | config/career.toml, config/sources.local.toml, config/.env, profile/profile.md (all gitignored), run_log |
| career_inbox (FastAPI :8477) | opportunities.status/notes via career_inbox/actions.py ONLY; companies.lat/lon (geocode cache); run_log |

(Extend this table with every new writer. Nothing else writes to db/vault.)
