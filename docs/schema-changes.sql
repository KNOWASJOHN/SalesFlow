-- Hand-applied schema changes
--
-- This repository has no migrations and no alembic: every environment's database
-- is changed by hand. This file is the append-only record of those changes, so
-- the next person setting up an environment knows what to run. Add new
-- statements at the bottom; never edit or remove an existing one.
--
-- The ORM models in app/models/ must stay in step with whatever has actually
-- been run. If a column is declared on a model but missing from the live table,
-- every insert into that table fails.
--
-- Nothing here runs automatically. Apply each block by hand, per environment,
-- before deploying the code that depends on it.


-- ---------------------------------------------------------------------------
-- 2026-09-26  Points ledger fields (admin & analytics endpoints, Step 4)
--
-- employee_points already served as the per-event ledger; these two columns make
-- each row self-describing instead of parsing the free-text "reason" column.
--
--   reason_code            purchase | rating | interaction | transfer
--   related_interaction_id the interaction the row concerns, when there is
--                          exactly one; NULL for aggregate and journey-level rows
--
-- Existing rows keep NULL in both columns and still count toward totals and
-- history. No backfill.
--
-- Required by app/models/employee_points.py. Without this, POST
-- /api/v1/journeys/{journey_id}/purchase and GET
-- /api/v1/employees/{employee_id}/points/history both answer 503.
-- ---------------------------------------------------------------------------

ALTER TABLE employee_points
    ADD COLUMN IF NOT EXISTS related_interaction_id UUID NULL
        REFERENCES interactions (interaction_id);

ALTER TABLE employee_points
    ADD COLUMN IF NOT EXISTS reason_code VARCHAR(20) NULL;
