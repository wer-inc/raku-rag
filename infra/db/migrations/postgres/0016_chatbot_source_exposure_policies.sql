-- ChatBot source exposure policies: tenant-scoped collection-wide ChatBot RAG enablement.
SET search_path TO public;

CREATE TABLE IF NOT EXISTS chatbot_source_exposure_policies (
  tenant_id text NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
  policy_id text NOT NULL,
  source_id text NOT NULL DEFAULT '',
  collection_id text NOT NULL DEFAULT '',
  exposure_mode text NOT NULL DEFAULT 'disabled'
    CHECK (exposure_mode IN ('disabled', 'internal_authenticated',
                             'external_authenticated', 'external_anonymous')),
  allowed_channels text[] NOT NULL DEFAULT ARRAY[]::text[],
  allowed_scenario_ids text[] NOT NULL DEFAULT ARRAY[]::text[],
  allowed_intents text[] NOT NULL DEFAULT ARRAY[]::text[],
  required_document_tags text[] NOT NULL DEFAULT ARRAY[]::text[],
  blocked_document_tags text[] NOT NULL DEFAULT ARRAY[]::text[],
  require_approved_effective boolean NOT NULL DEFAULT true,
  allow_obsolete_primary_evidence boolean NOT NULL DEFAULT false,
  allowed_domains text[] NOT NULL DEFAULT ARRAY[]::text[],
  status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'draft', 'archived')),
  unsupported_reason text NOT NULL DEFAULT '',
  updated_by text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, policy_id)
);

CREATE INDEX IF NOT EXISTS idx_chatbot_source_exposure_collection
  ON chatbot_source_exposure_policies (tenant_id, collection_id, status, updated_at DESC);

ALTER TABLE chatbot_source_exposure_policies ENABLE ROW LEVEL SECURITY;
ALTER TABLE chatbot_source_exposure_policies FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_isolation_chatbot_source_exposure_policies
  ON chatbot_source_exposure_policies;

CREATE POLICY tenant_isolation_chatbot_source_exposure_policies
  ON chatbot_source_exposure_policies
  USING (tenant_id = raku.current_tenant_id())
  WITH CHECK (tenant_id = raku.current_tenant_id());

GRANT SELECT, INSERT, UPDATE, DELETE
  ON chatbot_source_exposure_policies
  TO raku_app;
