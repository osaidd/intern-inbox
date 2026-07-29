CREATE TABLE run_log (
  id INTEGER PRIMARY KEY,
  skill TEXT NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  trigger TEXT CHECK (trigger IN ('manual','scheduled','button')),
  status TEXT CHECK (status IN ('ok','error','partial')),
  summary TEXT,
  output_path TEXT,
  metrics_json TEXT,
  feedback TEXT
);
