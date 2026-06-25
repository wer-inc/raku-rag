ALTER TABLE source_sync_states DROP CONSTRAINT IF EXISTS source_sync_states_status_check;
ALTER TABLE source_sync_states ADD CONSTRAINT source_sync_states_status_check
  CHECK (status IN ('idle', 'queued', 'observing', 'syncing', 'failed'));

ALTER TABLE source_sync_states DROP CONSTRAINT IF EXISTS source_sync_states_pkey;
ALTER TABLE source_sync_states ADD CONSTRAINT source_sync_states_pkey PRIMARY KEY (source_id);

DROP INDEX IF EXISTS idx_data_sources_tenant_collection_status;

ALTER TABLE data_sources DROP CONSTRAINT IF EXISTS data_sources_pkey;
ALTER TABLE data_sources ADD CONSTRAINT data_sources_pkey PRIMARY KEY (source_id);
