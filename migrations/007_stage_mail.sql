-- Stage tracking + mail scan (spec 2026-09-04): append-only stage history,
-- factual contact log, mail seen-ledger, suggestion queue, company mail domains.
-- The mail scan NEVER mutates opportunities: stage changes land only through
-- career_inbox/actions.py when the user confirms a suggestion.
-- (No BEGIN/COMMIT here — db.migrate() wraps each file in one transaction.)

CREATE TABLE company_domains (
  id INTEGER PRIMARY KEY,
  company_id INTEGER NOT NULL REFERENCES companies(id),
  domain TEXT NOT NULL UNIQUE,          -- lowercase registrable domain, e.g. 'ramp.com'
  source TEXT NOT NULL CHECK (source IN ('website','url','user','learned')),
  created_at TEXT NOT NULL
);
CREATE INDEX idx_company_domains_co ON company_domains(company_id);

CREATE TABLE email_messages (            -- seen-ledger: every message ever fetched
  id INTEGER PRIMARY KEY,
  dedupe_key TEXT NOT NULL UNIQUE,       -- gm_msgid > message_id > content hash
  gm_msgid TEXT,
  message_id TEXT,
  folder TEXT NOT NULL CHECK (folder IN ('inbox','sent')),
  from_addr TEXT,
  to_addrs TEXT,
  subject TEXT,
  sent_at TEXT,                          -- Date header, naive local ISO
  matched_company_id INTEGER REFERENCES companies(id),
  classification TEXT,                   -- rule verdict, or 'unmatched'
  processed_at TEXT NOT NULL
);

CREATE TABLE suggestions (
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL CHECK (kind IN
    ('set_applied','set_interviewing','set_offer','set_rejected')),
  opportunity_id INTEGER NOT NULL REFERENCES opportunities(id),
  company_id INTEGER REFERENCES companies(id),
  email_message_id INTEGER REFERENCES email_messages(id),
  evidence TEXT,                         -- one human line: sender, subject, date
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','accepted','dismissed')),
  created_at TEXT NOT NULL,
  resolved_at TEXT
);
CREATE INDEX idx_suggestions_open ON suggestions(status, opportunity_id);

CREATE TABLE stage_events (              -- append-only; written ONLY by actions.py + backfill
  id INTEGER PRIMARY KEY,
  opportunity_id INTEGER NOT NULL REFERENCES opportunities(id),
  from_status TEXT,                      -- NULL on the backfill seed
  to_status TEXT NOT NULL,
  occurred_at TEXT NOT NULL,
  source TEXT NOT NULL CHECK (source IN ('ui','skill','mail-confirm','backfill')),
  note TEXT,
  suggestion_id INTEGER REFERENCES suggestions(id)
);
CREATE INDEX idx_stage_events_opp ON stage_events(opportunity_id, occurred_at);

CREATE TABLE contact_events (            -- the "last touch" truth: factual only
  id INTEGER PRIMARY KEY,
  company_id INTEGER REFERENCES companies(id),
  opportunity_id INTEGER REFERENCES opportunities(id),
  direction TEXT NOT NULL CHECK (direction IN ('out','in')),
  channel TEXT NOT NULL CHECK (channel IN ('email','manual')),
  occurred_at TEXT NOT NULL,             -- email Date (local) or user-entered date
  subject TEXT,
  snippet TEXT,                          -- <=200 chars, storage-minimal by design
  message_id TEXT,
  created_by TEXT NOT NULL CHECK (created_by IN ('mail-scan','user')),
  created_at TEXT NOT NULL,
  CHECK (company_id IS NOT NULL OR opportunity_id IS NOT NULL)
);
CREATE INDEX idx_contact_events_co ON contact_events(company_id, occurred_at);
CREATE INDEX idx_contact_events_opp ON contact_events(opportunity_id, occurred_at);
CREATE UNIQUE INDEX idx_contact_events_msg ON contact_events(message_id)
  WHERE message_id IS NOT NULL;

-- Minimal honest backfill: one seed event per already-triaged row so every
-- timeline has an anchor. Date is approximate for anything but 'applied'.
INSERT INTO stage_events (opportunity_id, from_status, to_status, occurred_at, source, note)
SELECT id, NULL, status, COALESCE(applied_date, discovered_date, date('now')), 'backfill',
       'seeded from existing row (date approximate)'
FROM opportunities WHERE status != 'new';
