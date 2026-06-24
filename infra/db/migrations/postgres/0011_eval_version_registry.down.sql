SET search_path TO public;
ALTER TABLE evaluation_runs
  DROP COLUMN IF EXISTS version_registry;
