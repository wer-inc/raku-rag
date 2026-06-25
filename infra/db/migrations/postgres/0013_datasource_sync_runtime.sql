-- Datasource sync runtime hardening:
-- - datasource/source sync identifiers are tenant-scoped for SaaS multi-tenancy
-- - source_sync_states can represent completed and partial sync outcomes

ALTER TABLE data_sources DROP CONSTRAINT IF EXISTS data_sources_pkey;
ALTER TABLE data_sources ADD CONSTRAINT data_sources_pkey PRIMARY KEY (tenant_id, source_id);

CREATE INDEX IF NOT EXISTS idx_data_sources_tenant_collection_status
  ON data_sources (tenant_id, collection_id, status, updated_at DESC);

ALTER TABLE source_sync_states DROP CONSTRAINT IF EXISTS source_sync_states_pkey;
ALTER TABLE source_sync_states ADD CONSTRAINT source_sync_states_pkey PRIMARY KEY (tenant_id, source_id);

ALTER TABLE source_sync_states DROP CONSTRAINT IF EXISTS source_sync_states_status_check;
ALTER TABLE source_sync_states ADD CONSTRAINT source_sync_states_status_check
  CHECK (status IN ('idle', 'queued', 'observing', 'syncing', 'succeeded',
                    'partially_succeeded', 'failed'));
