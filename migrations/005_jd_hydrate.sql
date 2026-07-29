-- JD hydration (2026-07-28): attempt stamp so failed fetches aren't retried daily.
ALTER TABLE opportunities ADD COLUMN jd_fetched_at TEXT;
