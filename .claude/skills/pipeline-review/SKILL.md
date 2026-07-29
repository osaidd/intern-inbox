---
name: pipeline-review
description: Triage the internship pipeline from chat — a panel of every live job (priority, company stage/size, role, source, scores) with Kill / Shortlist / Revive plus funnel actions (Applied / Interviewing / Offer / Rejected). Kill marks status='dead', never deletes (the dedupe hash must survive future scans). Use when the user says "review the pipeline", "show me the jobs", "let me prune", "kill <id>", "shortlist <id>", "revive <id>", "applied to <id>", "interviewing at <id>", "offer from <id>", or "rejected by <id>". The local app at http://127.0.0.1:8477 (`uv run intern-inbox`) is the point-and-click equivalent.
---

# pipeline-review

Presentation-only: it shows stored numbers. No AI re-scoring here — judgment lives in
/skills-gap. Record start time first.

## Flow
1. **Gather rows** (one batch call):
   ```bash
   export PATH="$HOME/.local/bin:$PATH" && uv run python -c "
   import json, db
   conn = db.connect()
   rows = conn.execute(\"SELECT o.id, o.company, o.role, o.source, o.score, o.noc_fit_score, o.status, o.url, o.jd_text, o.priority, o.work_mode, c.stage, c.headcount, c.enrich_status FROM opportunities o LEFT JOIN companies c ON c.id = o.company_id WHERE o.status IN ('new','shortlisted','applied','interviewing') ORDER BY CASE o.priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 WHEN 'low' THEN 2 ELSE 3 END, COALESCE(o.score,0)+COALESCE(o.noc_fit_score,0) DESC\").fetchall()
   out = [{'id': r['id'], 'company': r['company'], 'role': r['role'],
           'source': r['source'], 'score': r['score'], 'noc': r['noc_fit_score'],
           'status': r['status'], 'url': r['url'],
           'priority': r['priority'], 'work_mode': r['work_mode'],
           'stage': r['stage'] if r['enrich_status'] == 'ok' else None,
           'headcount': r['headcount'] if r['enrich_status'] == 'ok' else None,
           'snippet': (r['jd_text'] or '')[:300]} for r in rows]
   conn.close()
   print(json.dumps(out))"
   ```
2. **Render the panel.** If the visualize MCP is available (`show_widget`; call its
   `read_me` first): an HTML table, one row per job — priority (color-coded), company,
   stage · size (`?` when unenriched), role (linked to url), work mode, source, score,
   NOC, expandable JD snippet — plus buttons **Kill** → `sendPrompt("kill <id>")` and
   **Shortlist** → `sendPrompt("shortlist <id>")`; on shortlisted rows show **Applied** →
   `sendPrompt("applied <id>")` and **Revive** → `sendPrompt("revive <id>")`; on applied
   rows show **Interviewing** / **Rejected**; on interviewing rows show **Offer** /
   **Rejected**. **Fallback** (widget tools unavailable, e.g. headless/CLI): print the
   ranked markdown table and instruct
   `reply: kill 3,5,9 · shortlist 2,7 · revive 4 · applied 6 · interviewing 6 · offer 6 · rejected 8`.
   Both paths drive the identical step-3 writes — the panel is presentation only.
3. **Apply actions** as commands arrive (batch per message) through the sanctioned status
   writer, `career_inbox.actions` — it validates the status and stamps `applied_date` for
   you:
   ```python
   from career_inbox.actions import set_status
   for i in ids: set_status(i, 'dead')   # kill
   ```
   - `kill` → `'dead'` · `shortlist` → `'shortlisted'` · `revive` → `'new'`
   - `applied` → `'applied'` (stamps `applied_date` on the first transition)
   - `interviewing` → `'interviewing'` · `offer` → `'offer'`
   - `rejected` → `'rejected'` (a rejection is funnel history, NOT a kill — it stays
     queryable separately from dead)
   After each batch, show `SELECT status, count(*) FROM opportunities GROUP BY status`.
4. **Record when the triage session ends:** `db.log_run(skill='pipeline-review', trigger='manual', status='ok', summary='<N killed, M shortlisted, A applied, K remain new>', started_at=..., finished_at=..., metrics_json='{"reviewed": R, "killed": N, "shortlisted": M, "revived": V, "applied": A, "interviewing": I, "offer": O, "rejected": J}')`.

## Rules
- Kill is a status flip, **NEVER `DELETE`** — the dedupe_hash must survive so the next
  scan skips jobs the user already rejected.
- Status writes go through `career_inbox.actions`, never a hand-rolled UPDATE.
- Show stored `score` / `noc_fit_score` as they are; `None` renders as "no signal", never
  0%. A row that has never been judged is not a bad row.
