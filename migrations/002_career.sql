-- The opportunities table: one row per posting, including jd_text — full job
-- descriptions are stored so applications can be tailored from them later.
CREATE TABLE opportunities (
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
    CHECK (status IN ('new','shortlisted','applied','dead')),
  dedupe_hash TEXT NOT NULL UNIQUE
);
