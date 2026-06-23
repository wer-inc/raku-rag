-- 002 Manufacturing Field Knowledge RAG domain schema.
-- Manufacturing metadata stays mirrored into 001 Document.metadata; these tables provide
-- production indexes, operational projections, review/audit references, and materialized KPIs.

SET search_path TO public;

CREATE TABLE IF NOT EXISTS manufacturing_factories (
  factory_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  factory_name text NOT NULL,
  access_scope text NOT NULL DEFAULT 'factory',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS manufacturing_production_lines (
  production_line_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  factory_id text NOT NULL,
  line_name text NOT NULL,
  access_scope text NOT NULL DEFAULT 'factory',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS manufacturing_processes (
  process_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  factory_id text NOT NULL,
  production_line_id text,
  process_name text NOT NULL,
  access_scope text NOT NULL DEFAULT 'process',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS manufacturing_equipment (
  equipment_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  factory_id text NOT NULL,
  process_id text,
  equipment_name text NOT NULL,
  model_no text NOT NULL DEFAULT '',
  access_scope text NOT NULL DEFAULT 'equipment',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS manufacturing_products (
  product_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  product_code text NOT NULL,
  product_name text NOT NULL,
  customer_id text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS manufacturing_parts (
  part_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  part_no text NOT NULL,
  part_name text NOT NULL DEFAULT '',
  product_id text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS manufacturing_customers (
  customer_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  customer_name_ref text NOT NULL,
  personal_data_category text NOT NULL DEFAULT 'customer_confidential',
  access_scope text NOT NULL DEFAULT 'customer',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS manufacturing_defect_types (
  defect_type_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  defect_code text NOT NULL,
  defect_name text NOT NULL,
  quality_category text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS manufacturing_failure_modes (
  failure_mode_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  failure_mode_name text NOT NULL,
  safety_category text NOT NULL DEFAULT '',
  quality_category text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS manufacturing_trouble_cases (
  trouble_case_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  factory_id text NOT NULL DEFAULT '',
  process_id text NOT NULL DEFAULT '',
  equipment_id text NOT NULL DEFAULT '',
  defect_type_id text NOT NULL DEFAULT '',
  failure_mode_id text NOT NULL DEFAULT '',
  occurred_at timestamptz,
  symptom_ref text NOT NULL DEFAULT '',
  cause_ref text NOT NULL DEFAULT '',
  recurrence_prevention_ref text NOT NULL DEFAULT '',
  source_document_ids text[] NOT NULL DEFAULT ARRAY[]::text[],
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS manufacturing_countermeasures (
  countermeasure_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  title text NOT NULL,
  type text NOT NULL DEFAULT 'candidate' CHECK (type IN ('reference', 'candidate')),
  measure_class text NOT NULL DEFAULT 'unknown' CHECK (
    measure_class IN ('provisional', 'permanent', 'unknown')
  ),
  source_document_ids text[] NOT NULL DEFAULT ARRAY[]::text[],
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS manufacturing_trouble_case_countermeasures (
  trouble_case_countermeasure_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  trouble_case_id text NOT NULL,
  countermeasure_id text NOT NULL,
  relation_type text NOT NULL DEFAULT 'candidate' CHECK (relation_type IN ('reference', 'candidate')),
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS manufacturing_work_instructions (
  work_instruction_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  document_id text NOT NULL,
  factory_id text NOT NULL DEFAULT '',
  process_id text NOT NULL DEFAULT '',
  equipment_id text NOT NULL DEFAULT '',
  approval_status text NOT NULL DEFAULT 'approved' CHECK (
    approval_status IN ('draft', 'pending_review', 'approved', 'obsolete')
  ),
  effective_date date,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS manufacturing_inspection_checklists (
  inspection_checklist_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  document_id text NOT NULL,
  factory_id text NOT NULL DEFAULT '',
  process_id text NOT NULL DEFAULT '',
  equipment_id text NOT NULL DEFAULT '',
  status text NOT NULL DEFAULT 'draft' CHECK (
    status IN ('draft', 'in_review', 'approved', 'rejected', 'archived')
  ),
  source_artifact_id text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS manufacturing_quality_issues (
  quality_issue_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  product_id text,
  part_id text,
  customer_id text,
  defect_type_id text,
  status text NOT NULL DEFAULT 'open',
  source_document_ids text[] NOT NULL DEFAULT ARRAY[]::text[],
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS manufacturing_training_materials (
  training_material_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  document_id text NOT NULL,
  factory_id text NOT NULL DEFAULT '',
  department_id text NOT NULL DEFAULT '',
  status text NOT NULL DEFAULT 'draft' CHECK (
    status IN ('draft', 'in_review', 'approved', 'rejected', 'archived')
  ),
  source_artifact_id text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS manufacturing_document_metadata (
  metadata_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  document_id text NOT NULL,
  collection_id text NOT NULL DEFAULT '',
  factory_id text NOT NULL DEFAULT '',
  department_id text NOT NULL DEFAULT '',
  process_id text,
  equipment_id text,
  product_id text,
  part_id text,
  customer_id text,
  alarm_code text NOT NULL DEFAULT '',
  defect_type text NOT NULL DEFAULT '',
  document_kind text NOT NULL CHECK (
    document_kind IN (
      'work_instruction',
      'inspection',
      'quality_report',
      'trouble_report',
      'minutes',
      'ledger',
      'drawing',
      'training'
    )
  ),
  approval_status text NOT NULL DEFAULT 'draft' CHECK (
    approval_status IN ('draft', 'pending_review', 'approved', 'obsolete')
  ),
  approval_source text NOT NULL DEFAULT 'workflow' CHECK (
    approval_source IN ('imported', 'workflow')
  ),
  effective_date date,
  approved_by text,
  approved_at timestamptz,
  obsolete_at timestamptz,
  superseded_by text,
  safety_category text NOT NULL DEFAULT '',
  quality_category text NOT NULL DEFAULT '',
  hazard_tags text[] NOT NULL DEFAULT ARRAY[]::text[],
  approval_metadata_checksum text NOT NULL DEFAULT '',
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  tombstone boolean NOT NULL DEFAULT false,
  deleted_at timestamptz,
  no_train_policy_ref text NOT NULL DEFAULT 'default_no_train',
  retention_policy_ref text NOT NULL DEFAULT 'manufacturing_retention',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS manufacturing_draft_artifacts (
  artifact_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  artifact_type text NOT NULL CHECK (
    artifact_type IN ('checklist', 'trouble_report', 'quality_report', 'training', 'faq')
  ),
  status text NOT NULL DEFAULT 'draft' CHECK (
    status IN ('draft', 'in_review', 'approved', 'rejected', 'archived')
  ),
  created_by text NOT NULL DEFAULT 'ai' CHECK (created_by IN ('ai', 'user')),
  reviewer_id text,
  reviewer_group text,
  source_document_ids text[] NOT NULL DEFAULT ARRAY[]::text[],
  source_citations jsonb NOT NULL DEFAULT '[]'::jsonb,
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  audit_log_ref text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (NOT (created_by = 'ai' AND status = 'approved'))
);

CREATE TABLE IF NOT EXISTS manufacturing_audit_events (
  audit_event_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  actor_id text NOT NULL DEFAULT '',
  action text NOT NULL,
  resource_type text NOT NULL DEFAULT '',
  resource_id text NOT NULL DEFAULT '',
  factory_id text NOT NULL DEFAULT '',
  department_id text NOT NULL DEFAULT '',
  decision text NOT NULL DEFAULT '',
  safety_block_reason text CHECK (
    safety_block_reason IS NULL
    OR safety_block_reason IN ('approved_citation_missing', 'insufficient_evidence', 'other_block')
  ),
  citation_ids text[] NOT NULL DEFAULT ARRAY[]::text[],
  document_ids_used text[] NOT NULL DEFAULT ARRAY[]::text[],
  prev_hash text NOT NULL DEFAULT '',
  entry_hash text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS manufacturing_safety_decisions (
  safety_decision_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  query_id text NOT NULL DEFAULT '',
  high_risk boolean NOT NULL DEFAULT false,
  reason_codes text[] NOT NULL DEFAULT ARRAY[]::text[],
  classification_source text NOT NULL DEFAULT '' CHECK (
    classification_source IN ('', 'metadata', 'rule', 'keyword', 'llm')
  ),
  safety_block_reason text CHECK (
    safety_block_reason IS NULL
    OR safety_block_reason IN ('approved_citation_missing', 'insufficient_evidence', 'other_block')
  ),
  approved_effective_citation_present boolean NOT NULL DEFAULT false,
  obsolete_warning boolean NOT NULL DEFAULT false,
  draft_warning boolean NOT NULL DEFAULT false,
  requires_onsite_confirmation boolean NOT NULL DEFAULT false,
  source_citation_ids text[] NOT NULL DEFAULT ARRAY[]::text[],
  audit_log_ref text,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS manufacturing_kpi_values (
  kpi_value_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  collection_id text,
  factory_id text,
  department_id text,
  metric_name text NOT NULL,
  metric_value numeric(14,4) NOT NULL DEFAULT 0,
  dimensions jsonb NOT NULL DEFAULT '{}'::jsonb,
  source_audit_log_range text NOT NULL DEFAULT '',
  source_ingestion_run_id text NOT NULL DEFAULT '',
  dagster_run_id text,
  materialized_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS manufacturing_dashboard_metric_snapshots (
  snapshot_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  collection_id text,
  factory_id text,
  department_id text,
  metrics jsonb NOT NULL DEFAULT '{}'::jsonb,
  safety_telemetry jsonb NOT NULL DEFAULT '{}'::jsonb,
  source_ingestion_run_id text NOT NULL DEFAULT '',
  dagster_run_id text,
  materialized_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_mfg_metadata_filter
  ON manufacturing_document_metadata (
    tenant_id,
    collection_id,
    factory_id,
    department_id,
    process_id,
    equipment_id,
    alarm_code,
    document_kind,
    approval_status,
    tombstone
  );
CREATE INDEX IF NOT EXISTS idx_mfg_trouble_filter
  ON manufacturing_trouble_cases (tenant_id, factory_id, process_id, equipment_id, defect_type_id);
CREATE INDEX IF NOT EXISTS idx_mfg_audit_axis
  ON manufacturing_audit_events (tenant_id, factory_id, department_id, action, created_at);
CREATE INDEX IF NOT EXISTS idx_mfg_safety_decisions
  ON manufacturing_safety_decisions (tenant_id, high_risk, safety_block_reason, created_at);
CREATE INDEX IF NOT EXISTS idx_mfg_kpi_filter
  ON manufacturing_kpi_values (tenant_id, collection_id, factory_id, department_id, metric_name);
CREATE INDEX IF NOT EXISTS idx_mfg_snapshot_filter
  ON manufacturing_dashboard_metric_snapshots (
    tenant_id,
    collection_id,
    factory_id,
    department_id,
    materialized_at
  );

DO $$
DECLARE
  table_name text;
BEGIN
  FOREACH table_name IN ARRAY ARRAY[
    'manufacturing_factories',
    'manufacturing_production_lines',
    'manufacturing_processes',
    'manufacturing_equipment',
    'manufacturing_products',
    'manufacturing_parts',
    'manufacturing_customers',
    'manufacturing_defect_types',
    'manufacturing_failure_modes',
    'manufacturing_trouble_cases',
    'manufacturing_countermeasures',
    'manufacturing_trouble_case_countermeasures',
    'manufacturing_work_instructions',
    'manufacturing_inspection_checklists',
    'manufacturing_quality_issues',
    'manufacturing_training_materials',
    'manufacturing_document_metadata',
    'manufacturing_draft_artifacts',
    'manufacturing_audit_events',
    'manufacturing_safety_decisions',
    'manufacturing_kpi_values',
    'manufacturing_dashboard_metric_snapshots'
  ] LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', table_name);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', table_name);
    EXECUTE format('DROP POLICY IF EXISTS %I ON %I', table_name || '_tenant_isolation', table_name);
    EXECUTE format(
      'CREATE POLICY %I ON %I USING (tenant_id = raku.current_tenant_id()) WITH CHECK (tenant_id = raku.current_tenant_id())',
      table_name || '_tenant_isolation',
      table_name
    );
  END LOOP;
END $$;

GRANT SELECT, INSERT, UPDATE, DELETE ON
  manufacturing_factories,
  manufacturing_production_lines,
  manufacturing_processes,
  manufacturing_equipment,
  manufacturing_products,
  manufacturing_parts,
  manufacturing_customers,
  manufacturing_defect_types,
  manufacturing_failure_modes,
  manufacturing_trouble_cases,
  manufacturing_countermeasures,
  manufacturing_trouble_case_countermeasures,
  manufacturing_work_instructions,
  manufacturing_inspection_checklists,
  manufacturing_quality_issues,
  manufacturing_training_materials,
  manufacturing_document_metadata,
  manufacturing_draft_artifacts,
  manufacturing_audit_events,
  manufacturing_safety_decisions,
  manufacturing_kpi_values,
  manufacturing_dashboard_metric_snapshots
TO raku_app;
