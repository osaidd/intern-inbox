---
name: skills-gap
description: Candidacy gap engine — reads every live stored JD in the pipeline against the user's own `profile/profile.md`, then reports: market demand across those JDs, gaps clustered by role family with one concrete action each, and per-shortlisted-role fit briefs (met/missing skills + 2–3 moves to improve their odds for THAT role). Use when the user says "skills gap", "where am I falling short", "how close am I to <role>", or "run the gap report".
---

# skills-gap

Record start time first.

## Flow
1. **Profile gate:** if `profile/profile.md` is missing, stop and offer two paths — run
   `/setup` (it writes the profile from their resume), or seed the file here: ask for the
   resume, draft the profile per the contract below, SHOW the draft, and write the file
   only after explicit approval. Never analyze against a fabricated profile.
2. **Corpus pass** — one batch call; capture the counts for the report header and the JD
   text for step 3:
   ```bash
   export PATH="$HOME/.local/bin:$PATH" && uv run python -c "
   import json, db
   conn = db.connect()
   rows = [dict(r) for r in conn.execute(\"SELECT id, company, role, status, jd_text FROM opportunities WHERE status NOT IN ('dead','rejected') ORDER BY COALESCE(score,0)+COALESCE(noc_fit_score,0) DESC\").fetchall()]
   conn.close()
   live = [r for r in rows if (r['jd_text'] or '').strip()]
   print(json.dumps({'live_rows': len(rows), 'with_jd': len(live), 'no_jd': len(rows) - len(live),
                     'shortlisted': sum(1 for r in rows if r['status'] == 'shortlisted'),
                     'jds': [dict(r, jd_text=(r['jd_text'] or '')[:6000]) for r in live[:30]]}))"
   ```
   Empty pipeline (`with_jd == 0`) → say so honestly, write no report, and log an `ok`
   run with summary "pipeline empty".
3. **Demand pass (judgment):** read the returned JDs and extract the skills, tools, and
   experiences they actually demand. Tabulate `skill | JD count | % of JDs | have?` —
   "have?" comes from `profile/profile.md` only, never from assumption. Count a skill once
   per JD.
4. **Gaps:** rank the demanded-but-missing skills by JD count, cluster them by role family
   (e.g. AI/ML engineering · product · GTM/growth · data · ops), and for each top gap write
   ONE concrete action — a project to build, a resume phrasing, or a learning step —
   citing the specific companies and roles demanding it.
5. **Fit briefs:** for each `status='shortlisted'` row (cap 10 by combined score desc; note
   any overflow in Data notes — and re-query by id for any shortlisted row whose JD fell
   outside step 2's cap) write a brief grounded in that row's stored `jd_text` and in
   the user's real background as `profile/profile.md` states it: met skills, missing skills,
   and 2–3 moves specific to THAT role. Judge fit as a band (strong / partial / thin) — no
   invented percentages.
6. **Write the report** to `vault/outputs/career/skills-gap-YYYY-MM-DD.md` (create the dir
   if needed; overwrite the same-day file — one report per day) with EXACTLY:
   ```
   # Skills Gap — YYYY-MM-DD
   > based on N live JDs (M excluded: no jd_text; dead/rejected rows ignored) · profile: profile/profile.md
   ## Snapshot            — top 5 gaps + top 3 strengths, one line each
   ## Market demand       — table: skill | JD count | % | have?
   ## Gaps, ranked        — per gap: demand evidence (companies/roles), why it matters for THEIR targets, one concrete next action
   ## Your edge           — high-demand skills they already have; how to lead with them
   ## Shortlist fit briefs — per shortlisted role: fit band | met | missing | 2–3 moves for THIS role
   ## Profile suggestions — skills the JDs demand that profile.md doesn't list (the user approves any edit)
   ## Data notes          — excluded rows, staleness, JD cap overflow, briefs overflow
   ```
7. **Record:** `db.log_run(skill='skills-gap', trigger='manual', status='ok'|'partial', summary='<top gap: X; N roles briefed>', started_at=..., finished_at=..., output_path='<report path>', metrics_json='{"jds_analyzed": N, "excluded_no_jd": K, "gaps": G, "roles_briefed": R}')`. `partial` if the JD cap truncated the corpus or any fit brief was skipped.

## profile.md contract
```markdown
# Profile

> Ground truth for skills-gap and the NOC-fit pass. Edit freely; skills-gap reads
> "Skills I have" plus Experience and Projects.

## Skills I have
- <skill> — <optional evidence note>
(one per line)

## Experience
(free-form)

## Projects
(free-form)
```

## Rules
- Never edit `profile/profile.md` without the user's approval in the moment; the report
  only *suggests* additions.
- Every gap action and fit-brief move cites stored JDs (company + role). No fabricated
  market claims.
- A thin JD is "no signal", never a bad fit — say when the evidence is too thin to judge.
- Empty live pipeline → say so honestly, write no report, log an `ok` run with summary
  "pipeline empty".
