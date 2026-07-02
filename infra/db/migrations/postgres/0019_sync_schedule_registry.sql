-- S2-1 (#0034): auto-sync scheduler bootstrap registry.
--
-- The scheduler must discover WHICH tenants have scheduled datasources, but every tenant table
-- (including `tenants` itself) is RLS-forced to one `raku.current_tenant_id()` at a time, so a
-- cross-tenant scan is impossible by design. This registry keeps the SAME RLS posture (enabled +
-- forced) and adds ONE explicit, auditable escape: a session that sets the dedicated
-- `app.sync_scheduler` GUC may READ all rows (the policy's USING clause) — writes stay
-- tenant-bound via WITH CHECK. The table carries ONLY scheduling metadata
-- (tenant_id / source_id / sync_schedule) — never source config, credentials, or document data.
-- Rows are mirrored by the datasource repository on upsert and pruned by the scheduler when the
-- underlying (RLS-checked) datasource no longer resolves.
SET search_path TO public;

CREATE TABLE IF NOT EXISTS sync_schedule_registry (
  tenant_id text NOT NULL,
  source_id text NOT NULL,
  sync_schedule text NOT NULL DEFAULT '',
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, source_id)
);

ALTER TABLE sync_schedule_registry ENABLE ROW LEVEL SECURITY;
ALTER TABLE sync_schedule_registry FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_isolation_sync_schedule_registry ON sync_schedule_registry;
CREATE POLICY tenant_isolation_sync_schedule_registry
  ON sync_schedule_registry
  USING (
    tenant_id = raku.current_tenant_id()
    OR current_setting('app.sync_scheduler', true) = '1'
  )
  WITH CHECK (tenant_id = raku.current_tenant_id());

GRANT SELECT, INSERT, UPDATE, DELETE ON sync_schedule_registry TO raku_app;
