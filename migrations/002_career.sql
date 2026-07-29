-- Locked DDL from Life OS Build Kickoff, plus jd_text (approved deviation 2026-07-03:
-- full job descriptions stored for tailoring).
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
