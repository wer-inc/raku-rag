-- 002 production track / schema lock hardening:
-- policy/profile/visual/cost/job tables + tenant-scoped RLS.
--
-- This migration is PostgreSQL-only and assumes 0001_core_rls.sql has created tenants,
-- collections, documents, chunks, and raku.current_tenant_id().

SET search_path TO public;

CREATE TABLE IF NOT EXISTS visual_assets (
  asset_id text PRIMARY KEY,
  tenant_id text NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
  collection_id text NOT NULL REFERENCES collections(collection_id) ON DELETE CASCADE,
  document_id text NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
  source_id text,
  version integer NOT NULL DEFAULT 1,
  storage_uri text NOT NULL DEFAULT '',
  checksum text NOT NULL DEFAULT '',
  content_type text NOT NULL DEFAULT 'image/png',
  page_number integer NOT NULL DEFAULT 1,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  metadata_schema_version integer NOT NULL DEFAULT 1,
  tombstone boolean NOT NULL DEFAULT false,
  deleted_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS layout_regions (
  region_id text PRIMARY KEY,
  tenant_id text NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
  collection_id text NOT NULL REFERENCES collections(collection_id) ON DELETE CASCADE,
  document_id text NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
  asset_id text NOT NULL REFERENCES visual_assets(asset_id) ON DELETE CASCADE,
  page_number integer NOT NULL DEFAULT 1,
  region_type text NOT NULL DEFAULT 'text',
  bbox jsonb NOT NULL DEFAULT '{}'::jsonb,
  heading_path text[] NOT NULL DEFAULT ARRAY[]::text[],
  ocr_text text NOT NULL DEFAULT '',
  generated_caption_text text NOT NULL DEFAULT '',
  crop_uri text NOT NULL DEFAULT '',
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  metadata_schema_version integer NOT NULL DEFAULT 1,
  tombstone boolean NOT NULL DEFAULT false,
  deleted_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS crops (
  crop_id text PRIMARY KEY,
  tenant_id text NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
  collection_id text NOT NULL REFERENCES collections(collection_id) ON DELETE CASCADE,
  document_id text NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
  asset_id text NOT NULL REFERENCES visual_assets(asset_id) ON DELETE CASCADE,
  region_id text NOT NULL REFERENCES layout_regions(region_id) ON DELETE CASCADE,
  bbox jsonb NOT NULL DEFAULT '{}'::jsonb,
  crop_uri text NOT NULL DEFAULT '',
  redaction_policy_ref text NOT NULL DEFAULT 'inherit',
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  tombstone boolean NOT NULL DEFAULT false,
  deleted_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS embeddings (
  embedding_id text PRIMARY KEY,
  tenant_id text NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
  collection_id text NOT NULL REFERENCES collections(collection_id) ON DELETE CASCADE,
  target_type text NOT NULL CHECK (target_type IN ('chunk', 'layout_region', 'visual_asset')),
  target_id text NOT NULL,
  modality text NOT NULL CHECK (modality IN ('text', 'visual')),
  provider text NOT NULL DEFAULT '',
  model text NOT NULL DEFAULT '',
  model_version text NOT NULL DEFAULT '',
  vector_dimensions integer NOT NULL DEFAULT 1024,
  embedding vector(1024),
  tombstone boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS cost_records (
  cost_record_id text PRIMARY KEY,
  tenant_id text NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
  scope_type text NOT NULL CHECK (scope_type IN ('tenant', 'collection', 'query', 'job')),
  scope_id text NOT NULL,
  kind text NOT NULL,
  amount numeric NOT NULL DEFAULT 0,
  quantity numeric NOT NULL DEFAULT 0,
  unit text NOT NULL DEFAULT '',
  trace_id text NOT NULL DEFAULT '',
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS budgets (
  budget_id text PRIMARY KEY,
  tenant_id text NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
  scope_type text NOT NULL CHECK (scope_type IN ('tenant', 'collection', 'query', 'job')),
  scope_id text NOT NULL,
  limit_amount numeric,
  spent_amount numeric NOT NULL DEFAULT 0,
  currency text NOT NULL DEFAULT 'USD',
  period text NOT NULL DEFAULT 'monthly',
  status text NOT NULL DEFAULT 'active',
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS source_document_manifests (
  manifest_id text PRIMARY KEY,
  tenant_id text NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
  collection_id text NOT NULL REFERENCES collections(collection_id) ON DELETE CASCADE,
  source_id text NOT NULL,
  source_document_id text NOT NULL,
  document_id text NOT NULL,
  content_checksum text NOT NULL DEFAULT '',
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  status text NOT NULL DEFAULT 'observed',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, source_id, source_document_id)
);

CREATE TABLE IF NOT EXISTS asset_materialization_refs (
  asset_materialization_id text PRIMARY KEY,
  tenant_id text NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
  collection_id text NOT NULL REFERENCES collections(collection_id) ON DELETE CASCADE,
  source_id text NOT NULL,
  sync_run_id text NOT NULL,
  dagster_asset_key text NOT NULL,
  partition_key text NOT NULL,
  document_id text NOT NULL DEFAULT '',
  chunk_ids text[] NOT NULL DEFAULT ARRAY[]::text[],
  storage_uri text NOT NULL DEFAULT '',
  dagster_run_id text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS reindex_plans (
  reindex_plan_id text PRIMARY KEY,
  tenant_id text NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
  collection_id text NOT NULL REFERENCES collections(collection_id) ON DELETE CASCADE,
  source_id text,
  scope jsonb NOT NULL DEFAULT '{}'::jsonb,
  reason text NOT NULL DEFAULT 'manual',
  status text NOT NULL DEFAULT 'planned',
  affected_document_count integer NOT NULL DEFAULT 0,
  dagster_backfill_id text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS provider_policies (
  provider_policy_id text PRIMARY KEY,
  tenant_id text NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
  collection_id text,
  name text NOT NULL DEFAULT '',
  status text NOT NULL DEFAULT 'active',
  parser_mode text NOT NULL DEFAULT 'aws_only',
  allowed_parser_providers text[] NOT NULL DEFAULT ARRAY['aws_textract','tesseract']::text[],
  allowed_ocr_providers text[] NOT NULL DEFAULT ARRAY['aws_textract','tesseract']::text[],
  allowed_llm_providers text[] NOT NULL DEFAULT ARRAY['bedrock','customer_managed']::text[],
  allowed_embedding_providers text[] NOT NULL DEFAULT ARRAY['bedrock','customer_managed']::text[],
  allowed_rerank_providers text[] NOT NULL DEFAULT ARRAY['bedrock','customer_managed']::text[],
  allowed_regions text[] NOT NULL DEFAULT ARRAY[]::text[],
  zero_retention_required boolean NOT NULL DEFAULT true,
  no_train_required boolean NOT NULL DEFAULT true,
  cross_cloud_processing_allowed boolean NOT NULL DEFAULT false,
  customer_opt_in_required boolean NOT NULL DEFAULT true,
  customer_opt_in_status text NOT NULL DEFAULT 'pending',
  fallback_policy jsonb NOT NULL DEFAULT '{}'::jsonb,
  profile_version text NOT NULL DEFAULT '1',
  schema_version integer NOT NULL DEFAULT 1,
  effective_from timestamptz NOT NULL DEFAULT now(),
  deprecated_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS retrieval_profiles (
  retrieval_profile_id text PRIMARY KEY,
  tenant_id text NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
  collection_id text,
  name text NOT NULL DEFAULT '',
  status text NOT NULL DEFAULT 'active',
  metadata_filter_required boolean NOT NULL DEFAULT true,
  identifier_match_enabled boolean NOT NULL DEFAULT true,
  identifier_fields text[] NOT NULL DEFAULT ARRAY[]::text[],
  vector_search_enabled boolean NOT NULL DEFAULT true,
  vector_top_k integer NOT NULL DEFAULT 20,
  rerank_enabled boolean NOT NULL DEFAULT true,
  rerank_candidate_limit integer NOT NULL DEFAULT 50 CHECK (rerank_candidate_limit <= 80),
  final_context_limit integer NOT NULL DEFAULT 5 CHECK (final_context_limit BETWEEN 1 AND 12),
  minimum_evidence_count integer NOT NULL DEFAULT 1,
  fallback_behavior text NOT NULL DEFAULT 'insufficient_evidence',
  profile_version text NOT NULL DEFAULT '1',
  schema_version integer NOT NULL DEFAULT 1,
  effective_from timestamptz NOT NULL DEFAULT now(),
  deprecated_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (metadata_filter_required OR identifier_match_enabled OR vector_search_enabled = false)
);

CREATE TABLE IF NOT EXISTS logging_policies (
  logging_policy_id text PRIMARY KEY,
  tenant_id text NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
  collection_id text,
  name text NOT NULL DEFAULT '',
  status text NOT NULL DEFAULT 'active',
  raw_user_query_storage text NOT NULL DEFAULT 'disabled',
  raw_retrieved_context_storage text NOT NULL DEFAULT 'disabled',
  model_input_storage text NOT NULL DEFAULT 'disabled',
  model_output_storage text NOT NULL DEFAULT 'disabled',
  store_citation_ids boolean NOT NULL DEFAULT true,
  store_chunk_ids boolean NOT NULL DEFAULT true,
  store_prompt_template_version boolean NOT NULL DEFAULT true,
  store_model_metadata boolean NOT NULL DEFAULT true,
  store_latency boolean NOT NULL DEFAULT true,
  store_cost boolean NOT NULL DEFAULT true,
  production_sampling_rate numeric NOT NULL DEFAULT 1.0,
  profile_version text NOT NULL DEFAULT '1',
  schema_version integer NOT NULL DEFAULT 1,
  effective_from timestamptz NOT NULL DEFAULT now(),
  deprecated_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS embedding_jobs (
  embedding_job_id text PRIMARY KEY,
  tenant_id text NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
  collection_id text NOT NULL REFERENCES collections(collection_id) ON DELETE CASCADE,
  document_id text,
  provider_policy_id text,
  retrieval_profile_id text,
  status text NOT NULL DEFAULT 'queued',
  target_type text NOT NULL DEFAULT 'chunk',
  target_ids text[] NOT NULL DEFAULT ARRAY[]::text[],
  failure_reason text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS rerank_traces (
  rerank_trace_id text PRIMARY KEY,
  tenant_id text NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
  query_id text NOT NULL DEFAULT '',
  retrieval_profile_id text NOT NULL DEFAULT '',
  provider text NOT NULL DEFAULT '',
  model text NOT NULL DEFAULT '',
  candidate_count integer NOT NULL DEFAULT 0,
  final_context_count integer NOT NULL DEFAULT 0,
  latency_ms numeric NOT NULL DEFAULT 0,
  cost_amount numeric NOT NULL DEFAULT 0,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS provider_config_audit_events (
  provider_config_audit_event_id text PRIMARY KEY,
  tenant_id text NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
  collection_id text,
  event_type text NOT NULL,
  actor text NOT NULL DEFAULT '',
  reason text NOT NULL DEFAULT '',
  redacted_before jsonb NOT NULL DEFAULT '{}'::jsonb,
  redacted_after jsonb NOT NULL DEFAULT '{}'::jsonb,
  correlation_id text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS evaluation_runs (
  evaluation_run_id text PRIMARY KEY,
  tenant_id text NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
  collection_id text,
  status text NOT NULL DEFAULT 'queued',
  metrics jsonb NOT NULL DEFAULT '{}'::jsonb,
  security_checks jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_visual_assets_live
  ON visual_assets (tenant_id, collection_id, document_id, tombstone, deleted_at);
CREATE INDEX IF NOT EXISTS idx_layout_regions_live
  ON layout_regions (tenant_id, collection_id, document_id, asset_id, tombstone, deleted_at);
CREATE INDEX IF NOT EXISTS idx_crops_live
  ON crops (tenant_id, collection_id, document_id, asset_id, tombstone, deleted_at);
CREATE INDEX IF NOT EXISTS idx_embeddings_target
  ON embeddings (tenant_id, collection_id, target_type, target_id, modality, tombstone);
CREATE INDEX IF NOT EXISTS idx_embeddings_hnsw
  ON embeddings USING hnsw (embedding vector_cosine_ops)
  WHERE embedding IS NOT NULL AND tombstone = false;
CREATE INDEX IF NOT EXISTS idx_documents_identifier_hot_fields
  ON documents (
    tenant_id,
    ((metadata->>'equipment_id')),
    ((metadata->>'alarm_code')),
    ((metadata->>'property_id')),
    ((metadata->>'room_number')),
    ((metadata->>'contract_id')),
    ((metadata->>'fund_id')),
    ((metadata->>'isin')),
    ((metadata->>'invoice_id'))
  );
CREATE INDEX IF NOT EXISTS idx_provider_config_audit_events
  ON provider_config_audit_events (tenant_id, collection_id, event_type, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_reindex_plans_status
  ON reindex_plans (tenant_id, collection_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_evaluation_runs_status
  ON evaluation_runs (tenant_id, collection_id, status, created_at DESC);

ALTER TABLE visual_assets ENABLE ROW LEVEL SECURITY;
ALTER TABLE layout_regions ENABLE ROW LEVEL SECURITY;
ALTER TABLE crops ENABLE ROW LEVEL SECURITY;
ALTER TABLE embeddings ENABLE ROW LEVEL SECURITY;
ALTER TABLE cost_records ENABLE ROW LEVEL SECURITY;
ALTER TABLE budgets ENABLE ROW LEVEL SECURITY;
ALTER TABLE source_document_manifests ENABLE ROW LEVEL SECURITY;
ALTER TABLE asset_materialization_refs ENABLE ROW LEVEL SECURITY;
ALTER TABLE reindex_plans ENABLE ROW LEVEL SECURITY;
ALTER TABLE provider_policies ENABLE ROW LEVEL SECURITY;
ALTER TABLE retrieval_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE logging_policies ENABLE ROW LEVEL SECURITY;
ALTER TABLE embedding_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE rerank_traces ENABLE ROW LEVEL SECURITY;
ALTER TABLE provider_config_audit_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE evaluation_runs ENABLE ROW LEVEL SECURITY;

ALTER TABLE visual_assets FORCE ROW LEVEL SECURITY;
ALTER TABLE layout_regions FORCE ROW LEVEL SECURITY;
ALTER TABLE crops FORCE ROW LEVEL SECURITY;
ALTER TABLE embeddings FORCE ROW LEVEL SECURITY;
ALTER TABLE cost_records FORCE ROW LEVEL SECURITY;
ALTER TABLE budgets FORCE ROW LEVEL SECURITY;
ALTER TABLE source_document_manifests FORCE ROW LEVEL SECURITY;
ALTER TABLE asset_materialization_refs FORCE ROW LEVEL SECURITY;
ALTER TABLE reindex_plans FORCE ROW LEVEL SECURITY;
ALTER TABLE provider_policies FORCE ROW LEVEL SECURITY;
ALTER TABLE retrieval_profiles FORCE ROW LEVEL SECURITY;
ALTER TABLE logging_policies FORCE ROW LEVEL SECURITY;
ALTER TABLE embedding_jobs FORCE ROW LEVEL SECURITY;
ALTER TABLE rerank_traces FORCE ROW LEVEL SECURITY;
ALTER TABLE provider_config_audit_events FORCE ROW LEVEL SECURITY;
ALTER TABLE evaluation_runs FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_isolation_visual_assets ON visual_assets;
DROP POLICY IF EXISTS tenant_isolation_layout_regions ON layout_regions;
DROP POLICY IF EXISTS tenant_isolation_crops ON crops;
DROP POLICY IF EXISTS tenant_isolation_embeddings ON embeddings;
DROP POLICY IF EXISTS tenant_isolation_cost_records ON cost_records;
DROP POLICY IF EXISTS tenant_isolation_budgets ON budgets;
DROP POLICY IF EXISTS tenant_isolation_source_document_manifests ON source_document_manifests;
DROP POLICY IF EXISTS tenant_isolation_asset_materialization_refs ON asset_materialization_refs;
DROP POLICY IF EXISTS tenant_isolation_reindex_plans ON reindex_plans;
DROP POLICY IF EXISTS tenant_isolation_provider_policies ON provider_policies;
DROP POLICY IF EXISTS tenant_isolation_retrieval_profiles ON retrieval_profiles;
DROP POLICY IF EXISTS tenant_isolation_logging_policies ON logging_policies;
DROP POLICY IF EXISTS tenant_isolation_embedding_jobs ON embedding_jobs;
DROP POLICY IF EXISTS tenant_isolation_rerank_traces ON rerank_traces;
DROP POLICY IF EXISTS tenant_isolation_provider_config_audit_events ON provider_config_audit_events;
DROP POLICY IF EXISTS tenant_isolation_evaluation_runs ON evaluation_runs;

CREATE POLICY tenant_isolation_visual_assets ON visual_assets
  USING (tenant_id = raku.current_tenant_id()) WITH CHECK (tenant_id = raku.current_tenant_id());
CREATE POLICY tenant_isolation_layout_regions ON layout_regions
  USING (tenant_id = raku.current_tenant_id()) WITH CHECK (tenant_id = raku.current_tenant_id());
CREATE POLICY tenant_isolation_crops ON crops
  USING (tenant_id = raku.current_tenant_id()) WITH CHECK (tenant_id = raku.current_tenant_id());
CREATE POLICY tenant_isolation_embeddings ON embeddings
  USING (tenant_id = raku.current_tenant_id()) WITH CHECK (tenant_id = raku.current_tenant_id());
CREATE POLICY tenant_isolation_cost_records ON cost_records
  USING (tenant_id = raku.current_tenant_id()) WITH CHECK (tenant_id = raku.current_tenant_id());
CREATE POLICY tenant_isolation_budgets ON budgets
  USING (tenant_id = raku.current_tenant_id()) WITH CHECK (tenant_id = raku.current_tenant_id());
CREATE POLICY tenant_isolation_source_document_manifests ON source_document_manifests
  USING (tenant_id = raku.current_tenant_id()) WITH CHECK (tenant_id = raku.current_tenant_id());
CREATE POLICY tenant_isolation_asset_materialization_refs ON asset_materialization_refs
  USING (tenant_id = raku.current_tenant_id()) WITH CHECK (tenant_id = raku.current_tenant_id());
CREATE POLICY tenant_isolation_reindex_plans ON reindex_plans
  USING (tenant_id = raku.current_tenant_id()) WITH CHECK (tenant_id = raku.current_tenant_id());
CREATE POLICY tenant_isolation_provider_policies ON provider_policies
  USING (tenant_id = raku.current_tenant_id()) WITH CHECK (tenant_id = raku.current_tenant_id());
CREATE POLICY tenant_isolation_retrieval_profiles ON retrieval_profiles
  USING (tenant_id = raku.current_tenant_id()) WITH CHECK (tenant_id = raku.current_tenant_id());
CREATE POLICY tenant_isolation_logging_policies ON logging_policies
  USING (tenant_id = raku.current_tenant_id()) WITH CHECK (tenant_id = raku.current_tenant_id());
CREATE POLICY tenant_isolation_embedding_jobs ON embedding_jobs
  USING (tenant_id = raku.current_tenant_id()) WITH CHECK (tenant_id = raku.current_tenant_id());
CREATE POLICY tenant_isolation_rerank_traces ON rerank_traces
  USING (tenant_id = raku.current_tenant_id()) WITH CHECK (tenant_id = raku.current_tenant_id());
CREATE POLICY tenant_isolation_provider_config_audit_events ON provider_config_audit_events
  USING (tenant_id = raku.current_tenant_id()) WITH CHECK (tenant_id = raku.current_tenant_id());
CREATE POLICY tenant_isolation_evaluation_runs ON evaluation_runs
  USING (tenant_id = raku.current_tenant_id()) WITH CHECK (tenant_id = raku.current_tenant_id());

GRANT SELECT, INSERT, UPDATE, DELETE
  ON visual_assets, layout_regions, crops, embeddings, cost_records, budgets,
     source_document_manifests, asset_materialization_refs, reindex_plans,
     provider_policies, retrieval_profiles, logging_policies, embedding_jobs,
     rerank_traces, provider_config_audit_events, evaluation_runs
  TO raku_app;
