-- migrations/008_career_inbox.sql
-- Career-inbox (spec 2026-07-12): inline notes + re-sighting timestamp.
ALTER TABLE opportunities ADD COLUMN notes TEXT;
ALTER TABLE opportunities ADD COLUMN last_seen TEXT;
UPDATE opportunities SET last_seen = discovered_date WHERE last_seen IS NULL;
