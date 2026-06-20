-- 003 Real Estate Property Management domain schema.
-- Domain rows are tenant-owned; all real estate APIs still rely on 001 auth/RLS and 010 profiles.

SET search_path TO public;

CREATE TABLE IF NOT EXISTS real_estate_properties (
  property_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  property_name text NOT NULL,
  address_ref text NOT NULL DEFAULT '',
  branch_id text NOT NULL DEFAULT '',
  owner_id text,
  management_scope text NOT NULL DEFAULT 'managed',
  status text NOT NULL DEFAULT 'active',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS real_estate_buildings (
  building_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  property_id text NOT NULL,
  building_name text NOT NULL,
  address_ref text NOT NULL DEFAULT '',
  status text NOT NULL DEFAULT 'active',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS real_estate_units (
  unit_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  property_id text NOT NULL,
  building_id text,
  room_number text NOT NULL,
  unit_type text NOT NULL DEFAULT '',
  status text NOT NULL DEFAULT 'active',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS real_estate_owners (
  owner_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  owner_name_ref text NOT NULL,
  contact_ref text,
  personal_data_category text NOT NULL DEFAULT 'owner_contact',
  access_scope text NOT NULL DEFAULT 'property',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS real_estate_occupants (
  occupant_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  property_id text NOT NULL,
  unit_id text NOT NULL,
  occupant_name_ref text NOT NULL,
  contact_ref text,
  personal_data_category text NOT NULL DEFAULT 'occupant_contact',
  status text NOT NULL DEFAULT 'active',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS real_estate_lease_contracts (
  lease_contract_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  property_id text NOT NULL,
  unit_id text NOT NULL,
  occupant_id text,
  contract_start_date date,
  contract_end_date date,
  renewal_date date,
  approval_status text NOT NULL DEFAULT 'approved',
  effective_date date,
  source_document_id text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS real_estate_lease_terms (
  lease_term_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  lease_contract_id text NOT NULL,
  term_type text NOT NULL,
  term_value text NOT NULL,
  effective_date date,
  source_citation_id text NOT NULL DEFAULT '',
  approval_status_at_use text NOT NULL DEFAULT 'approved',
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS real_estate_management_agreements (
  management_contract_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  property_id text NOT NULL,
  owner_id text NOT NULL,
  effective_date date,
  approval_status text NOT NULL DEFAULT 'approved',
  source_document_id text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS real_estate_repair_cases (
  repair_case_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  property_id text NOT NULL,
  unit_id text,
  repair_category text NOT NULL DEFAULT '',
  equipment_type text NOT NULL DEFAULT '',
  incident_type text NOT NULL DEFAULT '',
  status text NOT NULL DEFAULT 'open',
  opened_at timestamptz,
  closed_at timestamptz,
  source_document_ids text[] NOT NULL DEFAULT ARRAY[]::text[],
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS real_estate_maintenance_requests (
  maintenance_request_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  property_id text NOT NULL,
  unit_id text,
  occupant_id text,
  owner_id text,
  received_at timestamptz,
  channel text NOT NULL DEFAULT '',
  symptom text NOT NULL DEFAULT '',
  status text NOT NULL DEFAULT 'open',
  repair_case_id text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS real_estate_inspection_reports (
  inspection_report_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  property_id text NOT NULL,
  unit_id text,
  inspection_date date,
  vendor_id text,
  source_document_id text NOT NULL DEFAULT '',
  approval_status text NOT NULL DEFAULT 'approved',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS real_estate_vendors (
  vendor_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  vendor_name text NOT NULL,
  service_category text NOT NULL DEFAULT '',
  access_scope text NOT NULL DEFAULT 'tenant',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS real_estate_estimates (
  estimate_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  repair_case_id text,
  vendor_id text,
  amount numeric(14,2),
  currency text NOT NULL DEFAULT 'JPY',
  document_id text NOT NULL,
  approval_status text NOT NULL DEFAULT 'approved',
  issued_at date,
  valid_until date,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS real_estate_invoices (
  invoice_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  repair_case_id text,
  vendor_id text,
  owner_id text,
  occupant_id text,
  amount numeric(14,2),
  currency text NOT NULL DEFAULT 'JPY',
  document_id text NOT NULL,
  approval_status text NOT NULL DEFAULT 'approved',
  issued_at date,
  due_date date,
  payment_status text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS real_estate_move_out_cases (
  move_out_case_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  property_id text NOT NULL,
  unit_id text NOT NULL,
  occupant_id text,
  move_out_date date,
  status text NOT NULL DEFAULT 'open',
  source_document_ids text[] NOT NULL DEFAULT ARRAY[]::text[],
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS real_estate_restoration_cases (
  restoration_case_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  property_id text NOT NULL,
  unit_id text NOT NULL,
  move_out_case_id text,
  repair_case_id text,
  restoration_items jsonb NOT NULL DEFAULT '[]'::jsonb,
  estimated_amount numeric(14,2),
  charged_amount numeric(14,2),
  burden_policy_ref text NOT NULL DEFAULT '',
  source_citations jsonb NOT NULL DEFAULT '[]'::jsonb,
  status text NOT NULL DEFAULT 'open',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS real_estate_inquiry_cases (
  inquiry_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  property_id text,
  unit_id text,
  occupant_id text,
  owner_id text,
  channel text NOT NULL DEFAULT '',
  question text NOT NULL DEFAULT '',
  status text NOT NULL DEFAULT 'open',
  response_artifact_id text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS real_estate_owner_reports (
  owner_report_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  property_id text NOT NULL,
  owner_id text NOT NULL,
  artifact_id text,
  status text NOT NULL DEFAULT 'draft',
  report_period text NOT NULL DEFAULT '',
  source_document_ids text[] NOT NULL DEFAULT ARRAY[]::text[],
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS real_estate_document_metadata (
  document_metadata_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  collection_id text NOT NULL,
  document_id text NOT NULL,
  property_id text,
  building_id text,
  unit_id text,
  room_number text,
  owner_id text,
  occupant_id text,
  lease_contract_id text,
  management_contract_id text,
  document_type text NOT NULL,
  contract_start_date date,
  contract_end_date date,
  renewal_date date,
  move_out_date date,
  repair_category text,
  incident_type text,
  equipment_type text,
  vendor_id text,
  approval_status text NOT NULL DEFAULT 'approved',
  approval_source text,
  approved_by text,
  approved_at timestamptz,
  effective_date date,
  obsolete_at timestamptz,
  superseded_by text,
  legal_risk_category text,
  contract_risk_category text,
  financial_risk_category text,
  personal_data_category text,
  owner_department text,
  branch_id text,
  access_scope text NOT NULL DEFAULT 'tenant',
  no_train_policy_ref text NOT NULL DEFAULT 'default_no_train',
  retention_policy_ref text NOT NULL DEFAULT 'real_estate_pm_retention',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, document_id)
);

CREATE TABLE IF NOT EXISTS real_estate_draft_reviews (
  review_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  artifact_id text NOT NULL,
  reviewer_id text,
  reviewer_group text,
  assigned_at timestamptz,
  reviewed_at timestamptz,
  review_comment text NOT NULL DEFAULT '',
  approval_decision text NOT NULL DEFAULT '',
  audit_log_ref text,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS real_estate_risk_decisions (
  risk_decision_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  query_id text,
  is_high_risk boolean NOT NULL,
  risk_categories text[] NOT NULL DEFAULT ARRAY[]::text[],
  reason_codes text[] NOT NULL DEFAULT ARRAY[]::text[],
  classification_source text NOT NULL DEFAULT '010_risk_policy',
  policy_version integer NOT NULL DEFAULT 1,
  audit_log_ref text,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS real_estate_gate_decisions (
  gate_decision_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  risk_decision_id text NOT NULL,
  blocked boolean NOT NULL DEFAULT false,
  block_reason text NOT NULL DEFAULT '',
  approved_effective_citation_present boolean NOT NULL DEFAULT false,
  review_required boolean NOT NULL DEFAULT true,
  obsolete_warning boolean NOT NULL DEFAULT false,
  draft_warning boolean NOT NULL DEFAULT false,
  source_citation_ids text[] NOT NULL DEFAULT ARRAY[]::text[],
  audit_log_ref text,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS real_estate_kpi_values (
  kpi_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  collection_id text,
  branch_id text,
  property_id text,
  metric_name text NOT NULL,
  metric_value numeric(14,4) NOT NULL DEFAULT 0,
  time_range text NOT NULL DEFAULT 'all',
  calculated_at timestamptz NOT NULL DEFAULT now(),
  source_audit_log_range text NOT NULL DEFAULT '',
  export_ref text
);

CREATE INDEX IF NOT EXISTS idx_re_properties_tenant_branch
  ON real_estate_properties (tenant_id, branch_id, property_id);
CREATE INDEX IF NOT EXISTS idx_re_units_tenant_property
  ON real_estate_units (tenant_id, property_id, unit_id);
CREATE INDEX IF NOT EXISTS idx_re_metadata_filter
  ON real_estate_document_metadata (
    tenant_id,
    branch_id,
    property_id,
    building_id,
    unit_id,
    owner_id,
    document_type,
    approval_status,
    personal_data_category
  );
CREATE INDEX IF NOT EXISTS idx_re_repairs_filter
  ON real_estate_repair_cases (tenant_id, property_id, unit_id, repair_category, status);
CREATE INDEX IF NOT EXISTS idx_re_inquiries_filter
  ON real_estate_inquiry_cases (tenant_id, property_id, unit_id, status);
CREATE INDEX IF NOT EXISTS idx_re_kpi_filter
  ON real_estate_kpi_values (tenant_id, branch_id, property_id, metric_name);

DO $$
DECLARE
  table_name text;
BEGIN
  FOREACH table_name IN ARRAY ARRAY[
    'real_estate_properties',
    'real_estate_buildings',
    'real_estate_units',
    'real_estate_owners',
    'real_estate_occupants',
    'real_estate_lease_contracts',
    'real_estate_lease_terms',
    'real_estate_management_agreements',
    'real_estate_repair_cases',
    'real_estate_maintenance_requests',
    'real_estate_inspection_reports',
    'real_estate_vendors',
    'real_estate_estimates',
    'real_estate_invoices',
    'real_estate_move_out_cases',
    'real_estate_restoration_cases',
    'real_estate_inquiry_cases',
    'real_estate_owner_reports',
    'real_estate_document_metadata',
    'real_estate_draft_reviews',
    'real_estate_risk_decisions',
    'real_estate_gate_decisions',
    'real_estate_kpi_values'
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
  real_estate_properties,
  real_estate_buildings,
  real_estate_units,
  real_estate_owners,
  real_estate_occupants,
  real_estate_lease_contracts,
  real_estate_lease_terms,
  real_estate_management_agreements,
  real_estate_repair_cases,
  real_estate_maintenance_requests,
  real_estate_inspection_reports,
  real_estate_vendors,
  real_estate_estimates,
  real_estate_invoices,
  real_estate_move_out_cases,
  real_estate_restoration_cases,
  real_estate_inquiry_cases,
  real_estate_owner_reports,
  real_estate_document_metadata,
  real_estate_draft_reviews,
  real_estate_risk_decisions,
  real_estate_gate_decisions,
  real_estate_kpi_values
TO raku_app;
