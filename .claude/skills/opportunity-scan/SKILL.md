---
name: opportunity-scan
description: NYC/NJ internship sourcing for the intern-inbox pipeline — job-alert email feed (IMAP), GitHub internship lists, Ashby/Greenhouse posting APIs, JobSpy boards, startup boards (YC, Wellfound, Built In NYC) via WebFetch, WebSearch catch-all, plus a company-enrichment pass (stage/headcount/office → priority recompute). Stores every posting WITH full job-description text, scores profile fit + NOC fit, writes a ranked shortlisting brief. Use when the user says "scan opportunities", "find NYC internships", "run the job scan", or asks what is new in the pipeline. NEVER scrapes linkedin.com — LinkedIn postings only enter via the alert-email feed.
---

# opportunity-scan

NYC/NJ metro **internships only** — both gates live in `career_hunt/score.py` and every
feed applies them at ingest. Never scrape linkedin.com: jobspy's `sites` list excludes
it, and no fetch, WebSearch, or enrichment lookup may point at it — job-alert *emails*
are the only sanctioned LinkedIn channel. Record start time first (run_log needs it).

Hard gates and priority live in `career_hunt`; read them from the config
(`career_hunt.config.load()` — the personal `config/career.toml` when it exists, the
tracked `config/career.example.toml` on a fresh clone). Remote roles are never stored;
non-internships are never stored; confirmed ≥100 people or later than Series B →
auto-dead; seed–Series A ≤100 = tier1, Series B ≤75 = tier2 (scored lower). The feeds
apply all of this automatically via `career_hunt.store.insert_job`.

## Flow
1. **Feeds (run all four; each writes its own run_log row):**
   `export PATH="$HOME/.local/bin:$PATH"`
   - `uv run python -m feeds.linkedin_mail_pull` — job-alert emails via IMAP: LinkedIn **plus Built In and Wellfound** in the same run (senders in the config's `[linkedin_mail]` / `[mail_sources]`; its summary breaks out `linkedin=/builtin=/wellfound=`). If it prints the `CAREER_IMAP_PASS missing` message, add `> mail: skipped (app password not set — run /setup)` to the brief header and count a downgrade.
   - `uv run python -m feeds.github_intern_pull` — curated internship lists (raw GitHub JSON).
   - `uv run python -m feeds.ats_pull` — Ashby + Greenhouse posting APIs (org slugs in `config/sources.toml` `[ats]`, overlaid by the gitignored `config/sources.local.toml`; full JD text at ingest). **Internships only — hard red line:** a row stays when ANY explicit intern signal exists (intern/co-op title, an 'Intern' employment type, or JD wording asserting the role IS an internship — the intern signal supersedes a full-time type label); rows with no intern signal anywhere are dropped. Never hand-insert non-intern ATS rows around it.
   - `uv run python -m feeds.jobspy_pull` — Indeed + Google Jobs.
   Capture each feed's stats line for the brief and metrics. (The app's **Check now**
   button runs these same feeds; right after a check, expect mostly dups.)
2. **Startup boards:** for each board target in `config/sources.toml` (each entry carries
   a `name` and a `url` — YC Work at a Startup, Wellfound, Built In NYC): WebFetch the
   board URL; on failure fall back to WebSearch and note the downgrade. Extract postings:
   company, role, url, location, posted date, JD text — **plus company stage/headcount
   when the board shows them** (Built In NYC and Wellfound usually do).
3. **Catch-all — WebSearch:** run the `[websearch].templates` queries from
   `config/sources.toml` (fill `{month} {year}`; the `{company}` template only for
   already-shortlisted companies). **ATS APIs are the preferred transport:** when a hit
   resolves to a careers page hosted on Ashby (`jobs.ashbyhq.com/<org>`) or Greenhouse
   (`boards.greenhouse.io/<org>` / `job-boards.greenhouse.io/<org>`), do NOT scrape the
   page — pull the board's free keyless JSON instead
   (`api.ashbyhq.com/posting-api/job-board/<org>`,
   `boards-api.greenhouse.io/v1/boards/<org>/jobs?content=true`: exact locations + full
   plain-text JDs) and append the slug to `config/sources.toml` `[ats]` so
   `feeds/ats_pull.py` keeps covering it deterministically. That file is communal — a new
   slug there is worth a PR; anything the user wants kept private goes in
   `config/sources.local.toml` instead.
4. **Insert (steps 2–3 finds):** one `uv run python` heredoc per batch, through the shared
   store (never raw INSERTs):
   ```python
   import db
   from career_hunt import config as ch_config
   from career_hunt.models import Job
   from career_hunt.store import get_or_create_company, insert_job
   cfg = ch_config.load(); conn = db.connect()
   # when the board showed stage/headcount, seed the company first:
   get_or_create_company(conn, company, hints={"stage": "seed", "headcount": 40, "enrich_source": "builtin_nyc"})
   outcome, pri = insert_job(conn, Job(company=company, role=role, url=url, source="<target name>|websearch", location=location, posted_date=posted_date, jd_text=jd_text), cfg)
   ```
   Then set the profile-fit score on new rows:
   `from feeds.jobspy_pull import score_job, load_config` →
   `UPDATE opportunities SET score=? WHERE dedupe_hash=?`.
5. **Company enrichment pass (cap 15/run):** `SELECT c.id, c.name FROM companies c WHERE c.enrich_status='pending' AND EXISTS (SELECT 1 FROM opportunities o WHERE o.company_id=c.id AND o.status NOT IN ('dead','rejected')) ORDER BY c.id DESC LIMIT 15`. For each company, resolve from free evidence — board metadata already captured, the YC directory, the company's own site via WebFetch, WebSearch snippets; **never linkedin.com**:
   - judge `stage` ('pre-seed'|'seed'|'series a'|'series b'|'series c+'|'public'|'unknown'), `headcount` (best-estimate int), `sector`, `website`, NYC-area `office_address` if findable; set `enrich_source` (where the facts came from), `enriched_at` (now), `enrich_status='ok'` (or `'failed'` after honest attempts — the row stays LOW-visible, never silently dropped).
   - geocode the office: `from career_hunt.geocode import geocode` → lat, lon (skip quietly on None).
   - write via `conn.execute("UPDATE companies SET ... WHERE id=?")`, then recompute: `from career_hunt.store import recompute_priorities; recompute_priorities(conn, cfg, company_id)` — report any rows it auto-killed (hard gates) in the brief.
6. **NOC-fit pass:** `SELECT id, company, role, jd_text FROM opportunities WHERE status='new' AND noc_fit_score IS NULL ORDER BY score DESC LIMIT 15`. Read the user's background from `profile/profile.md` and judge fit against THEIR profile — never a hard-coded thesis. `noc_fit_score` is 0..1, the equal-weighted mean of four judgments, each 0..1:
   - `nyc_confirmed` — the role is really in the NYC/NJ metro, not a remote listing wearing a NYC tag.
   - `profile_alignment` — sector, stack, and function line up with what `profile/profile.md` says the user has done and wants.
   - `host_plausible` — a small, early-stage company that plausibly hosts and supervises an intern.
   - `story_value` — the work would produce something concrete to talk about in the next interview.
   Write it with a one-line `thesis_notes` saying why it fits THIS user:
   `UPDATE opportunities SET noc_fit_score=?, thesis_notes=? WHERE id=?`.
   Skip the pass and say so in the brief if `profile/profile.md` is missing (run `/setup`).
7. **Brief:** write `vault/outputs/career/scan-YYYY-MM-DD.md` (create dir if needed):
```
# Opportunity Scan — YYYY-MM-DD
> mail: emails/found/new · github: found/new · ats: found/new · jobspy: found/new · boards: N (downgrades: ...) · websearch: N · enriched: N (auto-dead: N)
## Top 10 (by priority, then score + noc_fit)
| # | Priority | Company | Stage · size | Role | Score | NOC | Thesis | Link |
## New this run — full list
## Shortlist next
Tell any session: "shortlist <company or id>" · "kill <id>" — or use the app at http://127.0.0.1:8477.
```
8. **Record:** `db.log_run(skill='opportunity-scan', trigger='manual', status='ok'|'partial', summary='<N new (M high), top: Company — Role>', started_at=..., finished_at=..., output_path='<brief path>', metrics_json='{"mail_new": N, "github_new": N, "ats_new": N, "jobspy_new": N, "boards_new": N, "websearch_new": N, "enriched": N, "auto_dead": N, "noc_scored": N, "downgrades": [...]}')`. `partial` if any source failed or downgraded. (The four feeds each wrote their own run_log rows too — that is correct, not duplication.)

## Rules
- **Stage/size:** tier1 = pre-seed–Series A AND ≤100 people; tier2 = Series B AND ≤75 (scored lower); confirmed ≥100 people or later than Series B = auto-dead via `recompute_priorities` — never manually deleted (the dedupe hash must survive).
- Internships only, NYC/NJ only: the shared gates drop full-time, remote-only, and non-metro roles automatically; don't hand-insert around them.
- Never fabricate postings: only rows with a real URL or a named careers page enter the DB.
- Enrichment is evidence-based: cite `enrich_source`; when stage or size can't be confirmed, leave 'unknown' + `enrich_status='failed'` rather than guessing a kill.
- JD text is stored verbatim, truncated at 20,000 chars (the store enforces this).
- Scores are decision aids, not verdicts — the brief ranks, the user decides.
- Never scrape linkedin.com. The alert-email feed is the only LinkedIn path.
