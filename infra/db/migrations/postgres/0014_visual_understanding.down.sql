SET search_path TO public;

DROP INDEX IF EXISTS idx_chunks_structured_parent;
DROP INDEX IF EXISTS idx_chunks_structured_kind;
DROP INDEX IF EXISTS idx_layout_regions_structured;

ALTER TABLE visual_assets
  DROP COLUMN IF EXISTS extractor_version;

ALTER TABLE ingestion_runs
  DROP COLUMN IF EXISTS async_job_status,
  DROP COLUMN IF EXISTS async_job_id,
  DROP COLUMN IF EXISTS async_provider;
