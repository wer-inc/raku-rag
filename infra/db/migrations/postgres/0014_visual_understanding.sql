-- Visual/PDF understanding production support.
-- Additive: async document-analysis state, extractor provenance, and structured visual indexes.
SET search_path TO public;

-- Re-assert the tenant-scoped source sync primary key for deployments that were created before 0013
-- was applied. This keeps PostgresIngestionRunStore's tenant-scoped upsert valid.
ALTER TABLE source_sync_states DROP CONSTRAINT IF EXISTS source_sync_states_pkey;
ALTER TABLE source_sync_states
  ADD CONSTRAINT source_sync_states_pkey PRIMARY KEY (tenant_id, source_id);

ALTER TABLE ingestion_runs
  ADD COLUMN IF NOT EXISTS async_provider   text NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS async_job_id     text NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS async_job_status text NOT NULL DEFAULT '';

ALTER TABLE visual_assets
  ADD COLUMN IF NOT EXISTS extractor_version text NOT NULL DEFAULT '';

CREATE INDEX IF NOT EXISTS idx_layout_regions_structured
  ON layout_regions USING gin ((metadata -> 'structured_content'));

CREATE INDEX IF NOT EXISTS idx_chunks_structured_kind
  ON chunks ((metadata->>'structured_kind'))
  WHERE metadata ? 'structured_kind' AND NOT tombstone;

CREATE INDEX IF NOT EXISTS idx_chunks_structured_parent
  ON chunks ((metadata->>'structured_parent_id'), (metadata->>'structured_kind'))
  WHERE metadata ? 'structured_parent_id' AND NOT tombstone;
