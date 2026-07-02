-- Rollback 0019_sync_schedule_registry.
SET search_path TO public;

DROP TABLE IF EXISTS sync_schedule_registry;
