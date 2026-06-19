-- P0-T13 — enable pgvector on the local Postgres at first boot (RT3).
-- Phase 1 migrations (infra/db/migrations, run by the migration runner) build the actual schema.
CREATE EXTENSION IF NOT EXISTS vector;
