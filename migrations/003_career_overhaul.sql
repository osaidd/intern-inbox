-- migrations/003_career_overhaul.sql
-- Career-hunt overhaul (spec 2026-07-08): companies enrichment table + wider
-- opportunities (priority tiers, funnel statuses, office metadata).
-- No BEGIN/COMMIT here — db.migrate() wraps the file in one transaction.

CREATE TABLE companies (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  name_key TEXT NOT NULL UNIQUE,      -- normalized lowercase dedupe key
  stage TEXT,                         -- 'pre-seed'|'seed'|'series a'|'series b'|'series c+'|'public'|'unknown'
  headcount INTEGER,
  sector TEXT,
  website TEXT,
  hq_address TEXT,
  office_address TEXT,                -- NYC-area office if different from HQ
  office_area TEXT,                   -- neighborhood/borough label
  lat REAL,
  lon REAL,
  enrich_status TEXT NOT NULL DEFAULT 'pending'
    CHECK (enrich_status IN ('pending','ok','failed')),
  enrich_source TEXT,
  enriched_at TEXT,
  notes TEXT
);

CREATE TABLE opportunities_new (
  id INTEGER PRIMARY KEY,
  source TEXT NOT NULL,
  company TEXT NOT NULL,
  role TEXT NOT NULL,
  url TEXT,
  location TEXT,
  posted_date TEXT,
  discovered_date TEXT NOT NULL DEFAULT (date('now')),
  jd_text TEXT,
  score REAL,
  noc_fit_score REAL,
  thesis_notes TEXT,
  diligence_brief_path TEXT,
  status TEXT NOT NULL DEFAULT 'new'
    CHECK (status IN ('new','shortlisted','applied','interviewing','offer','rejected','dead')),
  dedupe_hash TEXT NOT NULL UNIQUE,
  priority TEXT CHECK (priority IS NULL OR priority IN ('high','medium','low')),
  company_id INTEGER REFERENCES companies(id),
  work_mode TEXT CHECK (work_mode IS NULL OR work_mode IN ('onsite','hybrid','remote','unknown')),
  office_area TEXT,
  applied_date TEXT
);

INSERT INTO opportunities_new (id, source, company, role, url, location, posted_date,
  discovered_date, jd_text, score, noc_fit_score, thesis_notes, diligence_brief_path,
  status, dedupe_hash)
SELECT id, source, company, role, url, location, posted_date, discovered_date,
  jd_text, score, noc_fit_score, thesis_notes, diligence_brief_path, status, dedupe_hash
FROM opportunities;

DROP TABLE opportunities;
ALTER TABLE opportunities_new RENAME TO opportunities;
