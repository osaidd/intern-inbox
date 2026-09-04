# intern-inbox — conventions

## Fresh install? Take the wheel.
The app self-onboards now: with no `config/career.toml` the inbox redirects to
the 3-step wizard at `/welcome.html`, which writes a working config on its own.
So the fresh-install move is not rescue, it is depth — offer `/setup` as the
layer on top of the wizard's answers: keywords and rankings derived from their
actual resume, `profile/profile.md`, the job-alert walkthrough. Whatever their
first message says — "hi", "what is this?", anything — greet them, say `/setup`
is a ~15-minute conversation that reads their resume, and start the `setup`
skill as soon as they say yes. Do not wait for them to know the command. A
`config/career.toml` whose first line is `# written-by: intern-inbox-wizard` is
wizard-shallow, not personalized — same offer applies. Never surface raw
dependency or traceback output at them: fix quietly, summarize in one plain
sentence.

NYC/NJ **internships only** — the NYC/NJ metro gate is hard-coded in
`career_hunt/score.py`; internships-only is enforced in the same module's `matches()`
behind the `[hunt].interns_only` config flag (default true).
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
| feeds/jd_hydrate.py | opportunities (jd_text/score/priority/jd_fetched_at + zero-network score backfill for jd-bearing score-NULL rows), run_log |
| feeds/mail_scan.py (ATS/LinkedIn-notification + tracked-company reply scan; skill `mail-scan`; consent-gated by data/mail_scan_enabled; provider-agnostic via feeds/mail_auth) | email_messages, contact_events, suggestions (create/expire), company_domains (seed), run_log — NEVER opportunities.* |
| feeds/outlook_auth.py (Microsoft device-code sign-in; used by feeds/mail_auth + /api/outlook/*) | data/outlook_token.json only |
| opportunity-scan | vault/outputs/career/, opportunities, companies, run_log |
| add-opportunity | opportunities, companies, run_log |
| pipeline-review | opportunities.status (+applied_date) via career_inbox.actions.set_status(source='skill') ONLY — raw SQL would silently skip stage_events; run_log |
| skills-gap | vault/outputs/career/, profile/ (user-approved edits only), run_log |
| setup | config/career.toml, config/sources.local.toml, config/.env, profile/profile.md (all gitignored), run_log |
| career_inbox wizard (/welcome.html) | config/career.toml incl. [mail] provider, config/.env incl. CAREER_IMAP_HOST (gitignored; WIZARD_MARKER header); data/mail_scan_enabled consent marker (reply-scan checkbox) |
| career_inbox (FastAPI :8477) | opportunities.status/applied_date/notes/next_action_* + edit_job field corrections (company/role/url/location/salary_text/posted_date + derived dedupe_hash/company_id/work_mode/priority/score) via career_inbox/actions.py ONLY (actions also APPENDS stage_events on every status change, contact_events on manual log, company_domains on user add + accept-time learning, and resolves suggestions); companies.lat/lon (geocode cache); run_log; data/mail_scan_enabled consent marker (+ data/*_last_pull stamps); + /api/add → opportunities/companies via career_hunt.store (source=browser, no run_log — caller logs); /api/add-url → fetches the pasted URL then opportunities/companies via career_hunt.store + score (source=browser, one run_log `add-url`; linkedin.com never fetched — manual paste-assist instead; URL optional — manual fields store a postingless row with url NULL); /api/update → repo working tree via `git pull --ff-only` + `uv sync` (no db writes); /api/outlook/* → data/outlook_token.json via feeds/outlook_auth |

(Extend this table with every new writer. Nothing else writes to db/vault.)
