-- P1-3: durable manufacturing DataUsePolicy / no-train posture.

CREATE TABLE IF NOT EXISTS manufacturing_data_use_policies (
  tenant_id text PRIMARY KEY,
  no_train_default boolean NOT NULL DEFAULT true,
  training_opt_in boolean NOT NULL DEFAULT false,
  opt_in_contract_ref text,
  provider_no_train_required boolean NOT NULL DEFAULT true,
  no_train_fallback text NOT NULL DEFAULT 'block' CHECK (no_train_fallback IN ('block')),
  retention_customer integer NOT NULL DEFAULT 365,
  retention_audit integer NOT NULL DEFAULT 365,
  export_enabled boolean NOT NULL DEFAULT false,
  policy_version text NOT NULL DEFAULT '1',
  updated_by text,
  updated_at text
);

ALTER TABLE manufacturing_data_use_policies ENABLE ROW LEVEL SECURITY;
ALTER TABLE manufacturing_data_use_policies FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS manufacturing_data_use_policies_tenant_isolation
  ON manufacturing_data_use_policies;
CREATE POLICY manufacturing_data_use_policies_tenant_isolation
  ON manufacturing_data_use_policies
  USING (tenant_id = raku.current_tenant_id())
  WITH CHECK (tenant_id = raku.current_tenant_id());

GRANT SELECT, INSERT, UPDATE, DELETE ON manufacturing_data_use_policies TO raku_app;
