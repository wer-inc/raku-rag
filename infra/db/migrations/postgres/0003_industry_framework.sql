-- 010 Industry Solution Framework schema.
-- Shared seed rows use tenant_id='system'; customer overrides use their tenant_id.
-- RLS policy condition: tenant_id = raku.current_tenant_id() OR tenant_id = 'system'

SET search_path TO public;

CREATE TABLE IF NOT EXISTS industry_profiles (
  profile_id text PRIMARY KEY,
  tenant_id text NOT NULL DEFAULT 'system',
  industry_id text NOT NULL,
  name text NOT NULL,
  description text NOT NULL DEFAULT '',
  schema_version integer NOT NULL DEFAULT 1,
  profile_version integer NOT NULL DEFAULT 1,
  status text NOT NULL DEFAULT 'active',
  enabled_document_types jsonb NOT NULL DEFAULT '[]'::jsonb,
  workflow_definition_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
  risk_policy_id text NOT NULL DEFAULT '',
  required_evidence_policy_id text NOT NULL DEFAULT '',
  governance_profile_id text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, industry_id, profile_version)
);

CREATE TABLE IF NOT EXISTS metadata_schemas (
  schema_id text PRIMARY KEY,
  tenant_id text NOT NULL DEFAULT 'system',
  industry_id text NOT NULL,
  version integer NOT NULL,
  fields jsonb NOT NULL DEFAULT '{}'::jsonb,
  required_fields text[] NOT NULL DEFAULT ARRAY[]::text[],
  indexed_fields text[] NOT NULL DEFAULT ARRAY[]::text[],
  pii_fields text[] NOT NULL DEFAULT ARRAY[]::text[],
  retention_fields text[] NOT NULL DEFAULT ARRAY[]::text[],
  validation_rules jsonb NOT NULL DEFAULT '[]'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, industry_id, schema_id, version)
);

CREATE TABLE IF NOT EXISTS document_type_definitions (
  definition_id text PRIMARY KEY,
  tenant_id text NOT NULL DEFAULT 'system',
  industry_id text NOT NULL,
  document_type text NOT NULL,
  display_name text NOT NULL,
  required_metadata_fields text[] NOT NULL DEFAULT ARRAY[]::text[],
  default_approval_policy text NOT NULL DEFAULT 'default_approval',
  default_retention_policy text NOT NULL DEFAULT 'default_retention',
  default_access_scope text NOT NULL DEFAULT 'tenant',
  citation_policy text NOT NULL DEFAULT 'source_citation_required',
  UNIQUE (tenant_id, industry_id, document_type)
);

CREATE TABLE IF NOT EXISTS entity_type_definitions (
  definition_id text PRIMARY KEY,
  tenant_id text NOT NULL DEFAULT 'system',
  industry_id text NOT NULL,
  entity_type text NOT NULL,
  display_name text NOT NULL,
  id_field text NOT NULL,
  label_field text NOT NULL,
  relationship_fields text[] NOT NULL DEFAULT ARRAY[]::text[],
  metadata_fields text[] NOT NULL DEFAULT ARRAY[]::text[],
  UNIQUE (tenant_id, industry_id, entity_type)
);

CREATE TABLE IF NOT EXISTS workflow_definitions (
  workflow_id text PRIMARY KEY,
  tenant_id text NOT NULL DEFAULT 'system',
  industry_id text NOT NULL,
  name text NOT NULL,
  description text NOT NULL DEFAULT '',
  input_schema jsonb NOT NULL DEFAULT '{}'::jsonb,
  retrieval_profile text NOT NULL DEFAULT 'default',
  risk_policy_id text NOT NULL,
  required_evidence_policy_id text NOT NULL,
  output_schema jsonb NOT NULL DEFAULT '{}'::jsonb,
  draft_artifact_type text,
  review_required boolean NOT NULL DEFAULT false,
  audit_events text[] NOT NULL DEFAULT ARRAY[]::text[],
  kpi_events text[] NOT NULL DEFAULT ARRAY[]::text[],
  UNIQUE (tenant_id, industry_id, workflow_id)
);

CREATE TABLE IF NOT EXISTS risk_policies (
  policy_id text PRIMARY KEY,
  tenant_id text NOT NULL DEFAULT 'system',
  industry_id text NOT NULL,
  version integer NOT NULL DEFAULT 1,
  risk_categories text[] NOT NULL DEFAULT ARRAY[]::text[],
  metadata_rules jsonb NOT NULL DEFAULT '[]'::jsonb,
  keyword_rules jsonb NOT NULL DEFAULT '[]'::jsonb,
  intent_classification_rules jsonb NOT NULL DEFAULT '[]'::jsonb,
  llm_classifier_prompt text,
  default_action text NOT NULL DEFAULT 'allow',
  escalation_policy text NOT NULL DEFAULT 'human_review',
  uncertain_case_action text NOT NULL DEFAULT 'review_required',
  UNIQUE (tenant_id, industry_id, policy_id, version)
);

CREATE TABLE IF NOT EXISTS risk_decisions (
  risk_decision_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  query_id text NOT NULL DEFAULT '',
  industry_id text NOT NULL,
  risk_categories text[] NOT NULL DEFAULT ARRAY[]::text[],
  matched_rules text[] NOT NULL DEFAULT ARRAY[]::text[],
  confidence double precision NOT NULL DEFAULT 0,
  decision text NOT NULL,
  reason text NOT NULL DEFAULT '',
  policy_version integer NOT NULL DEFAULT 1,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS required_evidence_policies (
  policy_id text PRIMARY KEY,
  tenant_id text NOT NULL DEFAULT 'system',
  industry_id text NOT NULL,
  required_approval_status text NOT NULL DEFAULT 'approved',
  require_effective_date_valid boolean NOT NULL DEFAULT true,
  allow_obsolete_as_reference boolean NOT NULL DEFAULT false,
  allow_draft_as_reference boolean NOT NULL DEFAULT false,
  minimum_citation_count integer NOT NULL DEFAULT 1,
  citation_types_allowed text[] NOT NULL DEFAULT ARRAY[]::text[],
  insufficient_evidence_behavior text NOT NULL DEFAULT 'insufficient_evidence',
  UNIQUE (tenant_id, industry_id, policy_id)
);

CREATE TABLE IF NOT EXISTS approval_policies (
  policy_id text PRIMARY KEY,
  tenant_id text NOT NULL DEFAULT 'system',
  industry_id text NOT NULL,
  approval_statuses text[] NOT NULL DEFAULT ARRAY['draft','pending_review','approved','obsolete'],
  external_approval_source_allowed boolean NOT NULL DEFAULT true,
  lightweight_workflow_allowed boolean NOT NULL DEFAULT true,
  effective_date_required boolean NOT NULL DEFAULT true,
  obsolete_warning_required boolean NOT NULL DEFAULT true
);

CREATE TABLE IF NOT EXISTS acl_mapping_policies (
  policy_id text PRIMARY KEY,
  tenant_id text NOT NULL DEFAULT 'system',
  industry_id text NOT NULL,
  metadata_fields_to_acl text[] NOT NULL DEFAULT ARRAY[]::text[],
  role_mappings jsonb NOT NULL DEFAULT '{}'::jsonb,
  department_mappings jsonb NOT NULL DEFAULT '{}'::jsonb,
  resource_scope_rules jsonb NOT NULL DEFAULT '[]'::jsonb,
  deny_by_default boolean NOT NULL DEFAULT true,
  pre_filter_required boolean NOT NULL DEFAULT true
);

CREATE TABLE IF NOT EXISTS draft_artifact_type_definitions (
  definition_id text PRIMARY KEY,
  tenant_id text NOT NULL DEFAULT 'system',
  industry_id text NOT NULL,
  artifact_type text NOT NULL,
  display_name text NOT NULL,
  output_schema jsonb NOT NULL DEFAULT '{}'::jsonb,
  required_citations integer NOT NULL DEFAULT 1,
  review_required boolean NOT NULL DEFAULT true,
  auto_approve_allowed boolean NOT NULL DEFAULT false,
  retention_policy text NOT NULL DEFAULT 'default_retention',
  export_formats text[] NOT NULL DEFAULT ARRAY['json'],
  UNIQUE (tenant_id, industry_id, artifact_type)
);

CREATE TABLE IF NOT EXISTS draft_review_policies (
  policy_id text PRIMARY KEY,
  tenant_id text NOT NULL DEFAULT 'system',
  industry_id text NOT NULL,
  allowed_transitions jsonb NOT NULL DEFAULT '[]'::jsonb,
  reviewer_roles text[] NOT NULL DEFAULT ARRAY[]::text[],
  required_review_fields text[] NOT NULL DEFAULT ARRAY[]::text[],
  audit_required boolean NOT NULL DEFAULT true,
  multi_step_review_supported boolean NOT NULL DEFAULT false
);

CREATE TABLE IF NOT EXISTS draft_artifacts (
  artifact_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  industry_id text NOT NULL,
  artifact_type text NOT NULL,
  status text NOT NULL DEFAULT 'draft',
  created_by text NOT NULL DEFAULT 'ai',
  reviewer_id text,
  reviewer_group text,
  source_citations jsonb NOT NULL DEFAULT '[]'::jsonb,
  source_document_ids text[] NOT NULL DEFAULT ARRAY[]::text[],
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  generated_at timestamptz NOT NULL DEFAULT now(),
  template_id text,
  audit_log_ref text,
  CHECK (NOT (created_by = 'ai' AND status = 'approved'))
);

CREATE TABLE IF NOT EXISTS kpi_definitions (
  kpi_id text PRIMARY KEY,
  tenant_id text NOT NULL DEFAULT 'system',
  industry_id text NOT NULL,
  name text NOT NULL,
  description text NOT NULL DEFAULT '',
  formula text NOT NULL,
  event_sources text[] NOT NULL DEFAULT ARRAY[]::text[],
  aggregation_window text NOT NULL DEFAULT 'daily',
  dashboard_visibility text[] NOT NULL DEFAULT ARRAY['admin'],
  target_value double precision,
  UNIQUE (tenant_id, industry_id, kpi_id)
);

CREATE TABLE IF NOT EXISTS kpi_values (
  kpi_value_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  industry_id text NOT NULL,
  kpi_id text NOT NULL,
  value double precision NOT NULL,
  dimensions jsonb NOT NULL DEFAULT '{}'::jsonb,
  materialized_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS dashboard_widget_definitions (
  widget_id text PRIMARY KEY,
  tenant_id text NOT NULL DEFAULT 'system',
  industry_id text NOT NULL,
  name text NOT NULL,
  kpi_ids text[] NOT NULL DEFAULT ARRAY[]::text[],
  filters jsonb NOT NULL DEFAULT '{}'::jsonb,
  required_role text NOT NULL DEFAULT 'admin',
  data_source text NOT NULL DEFAULT 'audit',
  UNIQUE (tenant_id, industry_id, widget_id)
);

CREATE TABLE IF NOT EXISTS governance_profiles (
  governance_profile_id text PRIMARY KEY,
  tenant_id text NOT NULL DEFAULT 'system',
  industry_id text NOT NULL,
  no_train_policy_ref text NOT NULL DEFAULT 'default_no_train',
  audit_event_definitions text[] NOT NULL DEFAULT ARRAY[]::text[],
  retention_policy_refs text[] NOT NULL DEFAULT ARRAY['default_retention'],
  pii_policy_refs text[] NOT NULL DEFAULT ARRAY[]::text[],
  provider_governance_requirements text[] NOT NULL DEFAULT ARRAY['no_train_default','audit_required'],
  ai_governance_notes text[] NOT NULL DEFAULT ARRAY[]::text[],
  ismap_readiness_notes text[] NOT NULL DEFAULT ARRAY[]::text[]
);

CREATE TABLE IF NOT EXISTS audit_event_definitions (
  definition_id text PRIMARY KEY,
  tenant_id text NOT NULL DEFAULT 'system',
  industry_id text NOT NULL,
  event_type text NOT NULL,
  required_fields text[] NOT NULL DEFAULT ARRAY['tenant_id','actor_id','action','decision'],
  pii_redaction_required boolean NOT NULL DEFAULT true,
  retention_policy text NOT NULL DEFAULT 'default_retention',
  exportable boolean NOT NULL DEFAULT true,
  tenant_isolated boolean NOT NULL DEFAULT true,
  UNIQUE (tenant_id, industry_id, event_type)
);

CREATE TABLE IF NOT EXISTS evaluation_profiles (
  profile_id text PRIMARY KEY,
  tenant_id text NOT NULL DEFAULT 'system',
  industry_id text NOT NULL,
  metrics text[] NOT NULL DEFAULT ARRAY[]::text[],
  baseline_strategy text NOT NULL DEFAULT 'golden_set',
  hard_gates text[] NOT NULL DEFAULT ARRAY[]::text[],
  regression_gates text[] NOT NULL DEFAULT ARRAY[]::text[],
  evaluation_dataset_requirements text[] NOT NULL DEFAULT ARRAY[]::text[]
);

CREATE TABLE IF NOT EXISTS no_train_policies (
  policy_id text PRIMARY KEY,
  tenant_id text NOT NULL DEFAULT 'system',
  default_no_train boolean NOT NULL DEFAULT true,
  opt_in_required boolean NOT NULL DEFAULT true,
  applies_to text[] NOT NULL DEFAULT ARRAY['documents','metadata','query','answer','citation','draft','feedback','evaluation','log'],
  provider_capability_source text NOT NULL DEFAULT '001-provider-policy',
  customer_visible_description text NOT NULL DEFAULT '',
  audit_required boolean NOT NULL DEFAULT true,
  governance_status_ref text NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS document_metadata_extensions (
  extension_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  industry_id text NOT NULL,
  schema_id text NOT NULL,
  schema_version integer NOT NULL,
  document_id text NOT NULL,
  industry_metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  indexed_fields jsonb NOT NULL DEFAULT '{}'::jsonb,
  pii_fields jsonb NOT NULL DEFAULT '{}'::jsonb,
  no_train_policy_ref text NOT NULL DEFAULT 'default_no_train',
  retention_policy_ref text NOT NULL DEFAULT 'default_retention',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, industry_id, document_id, schema_id, schema_version)
);

CREATE INDEX IF NOT EXISTS idx_industry_profiles_lookup
  ON industry_profiles (tenant_id, industry_id, status);
CREATE INDEX IF NOT EXISTS idx_metadata_schemas_lookup
  ON metadata_schemas (tenant_id, industry_id, schema_id, version);
CREATE INDEX IF NOT EXISTS idx_document_metadata_extensions_doc
  ON document_metadata_extensions (tenant_id, industry_id, document_id);
CREATE INDEX IF NOT EXISTS idx_draft_artifacts_review
  ON draft_artifacts (tenant_id, industry_id, artifact_type, status);
CREATE INDEX IF NOT EXISTS idx_kpi_values_lookup
  ON kpi_values (tenant_id, industry_id, kpi_id, materialized_at DESC);

DO $$
DECLARE
  table_name text;
BEGIN
  FOREACH table_name IN ARRAY ARRAY[
    'industry_profiles',
    'metadata_schemas',
    'document_type_definitions',
    'entity_type_definitions',
    'workflow_definitions',
    'risk_policies',
    'risk_decisions',
    'required_evidence_policies',
    'approval_policies',
    'acl_mapping_policies',
    'draft_artifact_type_definitions',
    'draft_review_policies',
    'draft_artifacts',
    'kpi_definitions',
    'kpi_values',
    'dashboard_widget_definitions',
    'governance_profiles',
    'audit_event_definitions',
    'evaluation_profiles',
    'no_train_policies',
    'document_metadata_extensions'
  ]
  LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', table_name);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', table_name);
    EXECUTE format(
      'DROP POLICY IF EXISTS %I ON %I',
      table_name || '_tenant_or_system',
      table_name
    );
    EXECUTE format(
      'CREATE POLICY %I ON %I USING (tenant_id = raku.current_tenant_id() OR tenant_id = ''system'') WITH CHECK (tenant_id = raku.current_tenant_id() OR tenant_id = ''system'')',
      table_name || '_tenant_or_system',
      table_name
    );
    EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON %I TO raku_app', table_name);
  END LOOP;
END $$;
