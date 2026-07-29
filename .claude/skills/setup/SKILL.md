---
name: setup
description: First-run personalization for intern-inbox — interviews the user, ingests their resume, writes ALL personal config (career.toml, .env, profile.md), walks through Gmail app password + job-alert subscriptions, then smoke-tests a pull. Use on "/setup", "set me up", "get started", or when config/career.toml is missing. Re-runnable: with existing config it switches to update-my-profile mode.
---

# setup

Everything you write goes in GITIGNORED files: `config/career.toml`,
`config/sources.local.toml`, `config/.env`, `profile/profile.md`. NEVER write
personal values into tracked files. Record start time (run_log needs it).

If `config/career.toml` exists, say so and ask what to update (profile / roles /
email / boards) — do only that section, then re-run step 6.

## Flow
1. **Interview — one question at a time:**
   - Target role types (multiple choice: AI/SWE eng · product · GTM/growth ·
     data · ops/BizOps · other)
   - Strengths and standout skills (free text)
   - Dealbreakers (e.g. no crypto, no on-site-5-days, company types to avoid)
   - Dream companies (seed `config/sources.local.toml` with their Ashby/Greenhouse
     org slugs under `[ats]` if known, or add them to the `[role]`/`[scoring]`
     blocklist adjustments) — `feeds/config_load.py` merges this gitignored file
     over the communal `config/sources.toml` (lists union and dedupe, so it never
     needs to touch the tracked file)
   - Their email for job alerts + digests
2. **Resume:** ask them to drop a PDF into the repo folder or paste text. Read
   it. Derive: profile keywords (10-15 lowercase tokens), target titles
   (5-10), 2-3 sentence background summary.
3. **Write `profile/profile.md`:** background summary, education, skills,
   experience bullets, the derived keyword/title lists. This file is what
   opportunity-scan and skills-gap read as "who the user is".
4. **Write `config/career.toml`:** copy `config/career.example.toml`, then set
   `[role]` profile_keywords/target_titles from step 2, extend
   exclude_companies with their dealbreaker companies, set `[email] to` and
   `smtp_user` to their address. Write `config/.env` scaffold:
       CAREER_IMAP_PASS=   # Gmail app password — step 5

   **`[role]` and `[scoring]` MUST be written together.** `config/career.toml`
   carries the same three lists (profile_keywords, exclude_keywords,
   target_titles) in two sections: `[role]` is the hard include/exclude GATE
   (career_hunt.score), `[scoring]` is the profile-fit RANKING weight
   (feeds/jobspy_pull.score_job, feeds/jd_hydrate). They read independently, so
   whenever any of those three lists change for ANY reason — this step, a later
   "update my profile" run, or a manual edit — write the identical values into
   BOTH sections in the same edit. Never personalize one and leave the other on
   its example-file defaults: that silently splits what gets let through the
   gate from what gets ranked highly, and the drift is invisible until postings
   that should score well quietly don't (or vice versa).
5. **Manual steps — walk them through, wait for confirmation on each:**
   a. Gmail app password: myaccount.google.com/apppasswords (needs 2-Step
      Verification on) → create app password named "intern-inbox" → paste into
      config/.env as CAREER_IMAP_PASS. Never echo the password back in chat.
   b. Job alerts AT THEIR EMAIL (the mail feed parses only what lands in their
      inbox; alerts take up to a day to start flowing — say so):
      - linkedin.com/jobs → search each target title + "internship", location
        New York → toggle the alert bell (daily email)
      - builtin.com/nyc → create account → job alert for internships
      - wellfound.com → profile → email alert preferences
6. **Smoke test:** `uv run python -c "import db; db.migrate()"`, then
   `uv run python -m feeds.ats_pull` (communal boards — works with zero email
   setup), then `uv run intern-inbox` and open http://127.0.0.1:8477 — the ATS
   tab should show internships right now. If the mail password was set, also
   run `uv run python -m feeds.linkedin_mail_pull` (0 found is normal on day 1).
7. **Record:** `db.log_run(skill='setup', trigger='manual', status='ok',
   summary='profile + config written; smoke pull N rows', started_at=...,
   finished_at=...)`.
8. Tell them the daily loop: open the app → Check now → triage; "/skills-gap"
   after a few days of data; `git pull` occasionally for cohort updates.

## Rules
- The four personal files this skill writes are all covered by `.gitignore`
  (`config/career.toml`, `config/sources.local.toml`, `config/.env`,
  `profile/`) — never `git add` them, and if in doubt run
  `git check-ignore <path>` before writing to confirm it won't land in a commit.
- `config/career.example.toml` is the template — copy it, never edit it in
  place; it stays tracked and generic for every clone.
