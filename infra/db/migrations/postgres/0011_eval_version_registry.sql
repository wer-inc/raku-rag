-- 0011 (P2-10): persist model/prompt/dataset version provenance for every evaluation run.
-- The evaluation_runs table is already tenant-scoped and RLS-forced (0002); this additive JSONB
-- column inherits those policies and lets release gates prove which version triple was evaluated.
SET search_path TO public;
ALTER TABLE evaluation_runs
  ADD COLUMN IF NOT EXISTS version_registry jsonb NOT NULL DEFAULT '{}'::jsonb;
