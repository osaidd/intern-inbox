-- Follow-up reminders (2026-09-04): one optional next-action per row, set by
-- the user in the app, surfaced in the due strip once the date arrives.
-- (No BEGIN/COMMIT — db.migrate() wraps each file in one transaction.)
ALTER TABLE opportunities ADD COLUMN next_action_date TEXT;
ALTER TABLE opportunities ADD COLUMN next_action_note TEXT;
