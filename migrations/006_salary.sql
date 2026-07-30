-- migrations/006_salary.sql
-- Compensation summary straight from the board APIs (Ashby ships it when asked;
-- Greenhouse rarely). Display-only text, e.g. "$25 - $35 per hour".
ALTER TABLE opportunities ADD COLUMN salary_text TEXT;
