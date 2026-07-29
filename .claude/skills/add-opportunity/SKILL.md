---
name: add-opportunity
description: Paste-in intake for the internship pipeline — paste a job description, a posting URL, a forwarded job-alert email, or a loose list of roles; it parses, dedupes against the database, scores, stores everything with full JD text, and reports what changed. Use when the user pastes a JD or job link, says "add this job", "save this posting", "track this role", or pastes a job-alert email.
---

# add-opportunity

Intake anything job-shaped. Same pipeline as opportunity-scan: dedupe → score → store
with JD → run_log. Record start time first.

## Flow
1. **Parse the paste.** Forms: one JD blob · a bare URL · a forwarded job-alert email
   (often several postings) · a loose list. Per posting extract: company, role, url,
   location, posted_date if visible, jd_text (verbatim, ≤20,000 chars). A bare URL →
   WebFetch it first to get the JD. Never WebFetch a linkedin.com URL: ask the user to
   paste the JD text instead.
2. **Gate check — warn and ask BEFORE writing anything.** An explicit paste is intent, so
   these warn rather than block. Ask ONCE per batch, in one combined prompt listing every
   affected row; on "no", skip those rows and show them in the reply table as `skipped`:
   - **Not an internship** (`career_hunt.score.is_internship(role, jd_text)` is False):
     this pipeline is internships only — say so plainly before storing anything full-time.
   - **Exclude-keyword title** ("title matches exclude keyword 'senior'").
   - **Hard company gate** — `priority(...)` below returns `'dead'` (mega-corp / ≥100
     people / post-Series-B): store as `priority='low'` on yes.
3. **Dedupe + write** (one `uv run python` heredoc per batch):
   ```python
   import db
   from career_hunt import config as ch_config
   from career_hunt.models import Job, dedupe_hash
   from career_hunt.score import detect_work_mode, is_internship, priority
   from career_hunt.store import get_or_create_company
   from feeds.jobspy_pull import load_config, score_job
   ```
   `h = dedupe_hash(company, role, url)`, then:
   - new → link the company and stamp priority alongside the insert (a paste bypasses the
     ingest gates — see Rules — but still gets the company link and a priority so it ranks
     in the app):
     ```python
     ch = ch_config.load(); cfg = load_config(); conn = db.connect()
     cid = get_or_create_company(conn, company)
     comp = dict(conn.execute("SELECT stage, headcount FROM companies WHERE id=?", (cid,)).fetchone())
     pri = priority(Job(company=company, role=role, url=url, location=location, jd_text=jd_text), comp, ch)
     # pri == 'dead' is the hard-gate case from step 2 — only reached here on an explicit yes.
     db.insert("opportunities", {"source": source, "company": company, "role": role, "url": url, "location": location, "posted_date": posted_date, "jd_text": jd_text, "score": score_job(role, jd_text, posted_date, cfg), "dedupe_hash": h, "company_id": cid, "priority": pri if pri != 'dead' else 'low', "work_mode": detect_work_mode(location, jd_text)})
     ```
     — `source` is "paste", or "email-paste" for a forwarded alert email.
   - exists → UPDATE with exactly: `conn.execute("UPDATE opportunities SET jd_text=COALESCE(NULLIF(jd_text,''), ?), posted_date=COALESCE(?, posted_date) WHERE dedupe_hash=?", (new_jd_text, new_posted_date, h)); conn.commit()` — fills jd_text only where NULL/empty, refreshes posted_date only when the paste carries one; report "already tracked (id N, status S)".
4. **NOC pass** for newly added rows: same rubric as opportunity-scan (equal-weighted
   `nyc_confirmed` / `profile_alignment` / `host_plausible` / `story_value`, judged
   against the user's `profile/profile.md`) → `noc_fit_score` + one-line `thesis_notes`
   via `UPDATE ... WHERE id=?`. Skip it and say so if `profile/profile.md` is missing.
5. **Reply** with a compact table (id · priority · company · role · score · noc_fit ·
   new/updated) + pipeline counts by status
   (`SELECT status, count(*) FROM opportunities GROUP BY status`).
6. **Record:** `db.log_run(skill='add-opportunity', trigger='manual', status='ok', summary='<N added, M updated>', started_at=…, finished_at=…, metrics_json='{"added": N, "updated": M, "skipped": K}')`. Write this row even when nothing was added — 0 added / M updated / K skipped is still a run.

## Rules
- Never invent fields — unknown columns stay NULL. JD text verbatim, never summarized.
- No ingest gate here: pasting is the user deciding, so this skill does NOT go through
  `career_hunt.store.insert_job` (which enforces the ingest gates). It still links the
  company and stamps priority/work_mode so pasted rows rank correctly. Anything that
  would have been gated (non-internship, excluded title, mega-corp, ≥100 people,
  post-Series-B) → warn + ask once per batch; store as priority='low' on yes.
- A paste that is clearly an application-status email (rejection/interview), not a
  posting, is out of scope: say so and store nothing.
