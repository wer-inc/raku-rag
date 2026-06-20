-- 006 Investment Management / Mutual Fund domain schema.
-- Domain rows are tenant-owned; regulated workflows still inherit 001 RLS/auth and 010 policy contracts.

SET search_path TO public;

CREATE TABLE IF NOT EXISTS investment_funds (
  fund_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  fund_name text NOT NULL,
  fund_code text NOT NULL DEFAULT '',
  isin text NOT NULL DEFAULT '',
  association_code text NOT NULL DEFAULT '',
  asset_class text NOT NULL DEFAULT '',
  investment_region text NOT NULL DEFAULT '',
  investment_target text NOT NULL DEFAULT '',
  strategy_id text NOT NULL DEFAULT '',
  benchmark text NOT NULL DEFAULT '',
  currency_hedge_policy text NOT NULL DEFAULT '',
  risk_category text NOT NULL DEFAULT '',
  status text NOT NULL DEFAULT 'active',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS investment_fund_share_classes (
  share_class_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  fund_id text NOT NULL,
  currency text NOT NULL DEFAULT 'JPY',
  hedged_flag boolean NOT NULL DEFAULT false,
  distribution_policy text NOT NULL DEFAULT '',
  fee_class text NOT NULL DEFAULT '',
  effective_date date,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS investment_distribution_partners (
  distribution_partner_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  partner_name text NOT NULL,
  department_id text NOT NULL DEFAULT '',
  access_scope text NOT NULL DEFAULT 'tenant',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS investment_fund_documents (
  fund_document_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  document_id text NOT NULL,
  fund_id text,
  share_class_id text,
  document_type text NOT NULL,
  document_period text,
  report_date date,
  approval_status text NOT NULL DEFAULT 'approved',
  effective_date date,
  as_of_date date,
  source_uri text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS investment_prospectuses (
  prospectus_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  fund_id text NOT NULL,
  document_id text NOT NULL,
  document_type text NOT NULL,
  effective_date date,
  approval_status text NOT NULL DEFAULT 'approved',
  superseded_by text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS investment_fund_reports (
  report_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  fund_id text NOT NULL,
  document_id text NOT NULL,
  report_date date,
  document_period text NOT NULL DEFAULT '',
  performance_period text NOT NULL DEFAULT '',
  approval_status text NOT NULL DEFAULT 'approved',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS investment_monthly_reports (
  monthly_report_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  fund_id text NOT NULL,
  document_id text NOT NULL,
  report_date date,
  performance_period text NOT NULL DEFAULT '',
  approval_status text NOT NULL DEFAULT 'approved',
  source_citation_ids text[] NOT NULL DEFAULT ARRAY[]::text[],
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS investment_marketing_materials (
  marketing_material_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  fund_id text,
  document_id text NOT NULL,
  marketing_material_category text NOT NULL DEFAULT '',
  approval_status text NOT NULL DEFAULT 'draft',
  review_status text NOT NULL DEFAULT 'pending',
  compliance_review_id text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS investment_guidelines (
  guideline_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  fund_id text NOT NULL,
  restriction_type text NOT NULL,
  limit_value text NOT NULL DEFAULT '',
  effective_date date,
  approval_status text NOT NULL DEFAULT 'approved',
  source_document_id text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS investment_compliance_rules (
  compliance_rule_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  compliance_category text NOT NULL,
  rule_text_ref text NOT NULL DEFAULT '',
  document_id text NOT NULL DEFAULT '',
  effective_date date,
  approval_status text NOT NULL DEFAULT 'approved',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS investment_rfps (
  rfp_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  fund_id text,
  distribution_partner_id text,
  question_set jsonb NOT NULL DEFAULT '[]'::jsonb,
  response_artifacts text[] NOT NULL DEFAULT ARRAY[]::text[],
  status text NOT NULL DEFAULT 'open',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS investment_ddqs (
  ddq_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  fund_id text,
  question_set jsonb NOT NULL DEFAULT '[]'::jsonb,
  response_artifacts text[] NOT NULL DEFAULT ARRAY[]::text[],
  status text NOT NULL DEFAULT 'open',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS investment_inquiry_cases (
  inquiry_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  source_type text NOT NULL DEFAULT '',
  fund_id text,
  distribution_partner_id text,
  question text NOT NULL DEFAULT '',
  response_artifact_id text,
  status text NOT NULL DEFAULT 'open',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS investment_research_memos (
  memo_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  fund_id text,
  document_id text NOT NULL,
  confidential_data_category text NOT NULL DEFAULT 'research_memo',
  approval_status text NOT NULL DEFAULT 'approved',
  as_of_date date,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS investment_risk_reports (
  risk_report_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  fund_id text,
  document_id text NOT NULL,
  risk_category text NOT NULL DEFAULT '',
  approval_status text NOT NULL DEFAULT 'approved',
  as_of_date date,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS investment_esg_documents (
  esg_document_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  fund_id text,
  document_id text NOT NULL,
  esg_category text NOT NULL DEFAULT '',
  approval_status text NOT NULL DEFAULT 'approved',
  as_of_date date,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS investment_document_metadata (
  document_metadata_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  collection_id text NOT NULL,
  document_id text NOT NULL,
  fund_id text,
  fund_name text,
  fund_code text,
  share_class_id text,
  isin text,
  association_code text,
  asset_class text,
  investment_region text,
  investment_target text,
  investment_strategy text,
  benchmark text,
  currency_hedge_policy text,
  currency_hedge text,
  fee_type text,
  trust_fee text,
  risk_category text,
  risk_classification text,
  target_investor_category text,
  distribution_partner_id text,
  distributor_id text,
  document_type text NOT NULL,
  document_period text,
  report_date date,
  approval_status text NOT NULL DEFAULT 'approved',
  approval_source text,
  approved_by text,
  approved_at timestamptz,
  effective_date date,
  as_of_date date,
  obsolete_at timestamptz,
  superseded_by text,
  performance_period text,
  disclosure_category text,
  compliance_risk_category text,
  compliance_category text,
  marketing_material_category text,
  advice_boundary_category text,
  legal_risk_category text,
  regulated_activity_category text,
  confidential_data_category text,
  personal_data_category text,
  owner_department text,
  department_id text,
  role text,
  access_scope text NOT NULL DEFAULT 'tenant',
  no_train_policy_ref text NOT NULL DEFAULT 'default_no_train',
  retention_policy_ref text NOT NULL DEFAULT 'investment_regulated_retention',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, document_id)
);

CREATE TABLE IF NOT EXISTS investment_draft_reviews (
  review_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  artifact_id text NOT NULL,
  reviewer_id text,
  reviewer_group text,
  assigned_at timestamptz,
  reviewed_at timestamptz,
  review_state text NOT NULL DEFAULT 'in_review',
  review_comment text NOT NULL DEFAULT '',
  approval_decision text NOT NULL DEFAULT '',
  audit_log_ref text,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS investment_compliance_reviews (
  compliance_review_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  artifact_id text NOT NULL,
  reviewer_group text NOT NULL DEFAULT 'compliance_reviewers',
  review_state text NOT NULL DEFAULT 'pending',
  required_changes text[] NOT NULL DEFAULT ARRAY[]::text[],
  decision text NOT NULL DEFAULT '',
  audit_log_ref text,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS investment_disclosure_evidence (
  disclosure_evidence_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  artifact_id text NOT NULL,
  fund_id text,
  source_document_ids text[] NOT NULL DEFAULT ARRAY[]::text[],
  source_citation_ids text[] NOT NULL DEFAULT ARRAY[]::text[],
  contradiction_results jsonb NOT NULL DEFAULT '[]'::jsonb,
  status text NOT NULL DEFAULT 'ready',
  audit_log_ref text,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS investment_risk_decisions (
  risk_decision_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  query_id text,
  advice_boundary_triggered boolean NOT NULL DEFAULT false,
  regulated_activity_triggered boolean NOT NULL DEFAULT false,
  marketing_material_triggered boolean NOT NULL DEFAULT false,
  compliance_review_required boolean NOT NULL DEFAULT true,
  risk_categories text[] NOT NULL DEFAULT ARRAY[]::text[],
  decision text NOT NULL DEFAULT 'review_required',
  reason text NOT NULL DEFAULT '',
  policy_version integer NOT NULL DEFAULT 1,
  audit_log_ref text,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS investment_gate_decisions (
  gate_decision_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  risk_decision_id text NOT NULL,
  blocked boolean NOT NULL DEFAULT false,
  block_reason text NOT NULL DEFAULT '',
  approved_effective_citation_present boolean NOT NULL DEFAULT false,
  disclosure_evidence_present boolean NOT NULL DEFAULT false,
  compliance_review_required boolean NOT NULL DEFAULT true,
  source_citation_ids text[] NOT NULL DEFAULT ARRAY[]::text[],
  audit_log_ref text,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS investment_kpi_values (
  kpi_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  collection_id text,
  fund_id text,
  department_id text,
  document_type text,
  regulated_activity_category text,
  metric_name text NOT NULL,
  metric_value numeric(14,4) NOT NULL DEFAULT 0,
  time_range text NOT NULL DEFAULT 'all',
  calculated_at timestamptz NOT NULL DEFAULT now(),
  source_audit_log_range text NOT NULL DEFAULT '',
  export_ref text
);

CREATE INDEX IF NOT EXISTS idx_im_funds_tenant_code
  ON investment_funds (tenant_id, fund_id, fund_code, isin, association_code);
CREATE INDEX IF NOT EXISTS idx_im_metadata_filter
  ON investment_document_metadata (
    tenant_id,
    department_id,
    role,
    fund_id,
    fund_code,
    share_class_id,
    asset_class,
    distribution_partner_id,
    document_type,
    approval_status,
    confidential_data_category,
    personal_data_category,
    regulated_activity_category
  );
CREATE INDEX IF NOT EXISTS idx_im_draft_reviews_artifact
  ON investment_draft_reviews (tenant_id, artifact_id, review_state);
CREATE INDEX IF NOT EXISTS idx_im_compliance_reviews_artifact
  ON investment_compliance_reviews (tenant_id, artifact_id, review_state);
CREATE INDEX IF NOT EXISTS idx_im_disclosure_evidence_artifact
  ON investment_disclosure_evidence (tenant_id, artifact_id, status);
CREATE INDEX IF NOT EXISTS idx_im_kpi_filter
  ON investment_kpi_values (
    tenant_id,
    fund_id,
    department_id,
    document_type,
    regulated_activity_category,
    metric_name
  );

DO $$
DECLARE
  table_name text;
BEGIN
  FOREACH table_name IN ARRAY ARRAY[
    'investment_funds',
    'investment_fund_share_classes',
    'investment_distribution_partners',
    'investment_fund_documents',
    'investment_prospectuses',
    'investment_fund_reports',
    'investment_monthly_reports',
    'investment_marketing_materials',
    'investment_guidelines',
    'investment_compliance_rules',
    'investment_rfps',
    'investment_ddqs',
    'investment_inquiry_cases',
    'investment_research_memos',
    'investment_risk_reports',
    'investment_esg_documents',
    'investment_document_metadata',
    'investment_draft_reviews',
    'investment_compliance_reviews',
    'investment_disclosure_evidence',
    'investment_risk_decisions',
    'investment_gate_decisions',
    'investment_kpi_values'
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
  investment_funds,
  investment_fund_share_classes,
  investment_distribution_partners,
  investment_fund_documents,
  investment_prospectuses,
  investment_fund_reports,
  investment_monthly_reports,
  investment_marketing_materials,
  investment_guidelines,
  investment_compliance_rules,
  investment_rfps,
  investment_ddqs,
  investment_inquiry_cases,
  investment_research_memos,
  investment_risk_reports,
  investment_esg_documents,
  investment_document_metadata,
  investment_draft_reviews,
  investment_compliance_reviews,
  investment_disclosure_evidence,
  investment_risk_decisions,
  investment_gate_decisions,
  investment_kpi_values
TO raku_app;
