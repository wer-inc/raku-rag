-- 001 production track / Tier B bootstrap:
-- core tenant-scoped retrieval schema + pgvector + RLS.
--
-- This migration is PostgreSQL-only. It intentionally lives under
-- infra/db/migrations/postgres/ so the existing sqlite migration smoke does not apply it.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE SCHEMA IF NOT EXISTS raku;

CREATE OR REPLACE FUNCTION raku.current_tenant_id()
RETURNS text
LANGUAGE sql
STABLE
AS $$
  SELECT NULLIF(current_setting('app.current_tenant_id', true), '')
$$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'raku_app') THEN
    CREATE ROLE raku_app NOLOGIN;
  END IF;
END $$;

-- Create core tables in `public`, NOT the connecting role's schema. The Tier B gate connects as a
-- user that may share a name with the `raku` schema above; with the default search_path
-- ("$user", public) that would land unqualified tables in the role schema, and they then vanish
-- from the search_path after `SET ROLE raku_app` (caught by the Tier B RLS smoke in CI).
SET search_path TO public;

CREATE TABLE IF NOT EXISTS tenants (
  tenant_id text PRIMARY KEY,
  name text NOT NULL DEFAULT '',
  status text NOT NULL DEFAULT 'active',
  default_query_profile_id text,
  cost_budget numeric,
  retention_policy jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS query_profiles (
  profile_id text PRIMARY KEY,
  tenant_id text NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
  score_threshold double precision NOT NULL DEFAULT 0.10,
  top_k integer NOT NULL DEFAULT 5,
  minimum_evidence_count integer NOT NULL DEFAULT 1,
  rerank_enabled boolean NOT NULL DEFAULT true,
  rerank_top_n integer NOT NULL DEFAULT 50,
  query_rewrite_enabled boolean NOT NULL DEFAULT false,
  self_eval_enabled boolean NOT NULL DEFAULT true,
  llm_model text NOT NULL DEFAULT 'extractive-mvp',
  profile_version text NOT NULL DEFAULT '1',
  schema_version integer NOT NULL DEFAULT 1,
  effective_from timestamptz NOT NULL DEFAULT now(),
  deprecated_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS collections (
  collection_id text PRIMARY KEY,
  tenant_id text NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
  name text NOT NULL DEFAULT '',
  query_profile_id text REFERENCES query_profiles(profile_id),
  cost_budget numeric,
  sync_schedule text,
  stale_tolerance interval,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS data_sources (
  source_id text PRIMARY KEY,
  tenant_id text NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
  collection_id text NOT NULL REFERENCES collections(collection_id) ON DELETE CASCADE,
  type text NOT NULL,
  config jsonb NOT NULL DEFAULT '{}'::jsonb,
  sync_schedule text,
  last_synced_at timestamptz,
  status text NOT NULL DEFAULT 'active',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS documents (
  document_id text PRIMARY KEY,
  tenant_id text NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
  collection_id text NOT NULL REFERENCES collections(collection_id) ON DELETE CASCADE,
  source_id text,
  source_document_id text,
  version integer NOT NULL DEFAULT 1,
  checksum text NOT NULL DEFAULT '',
  content_checksum text,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  metadata_schema_version integer NOT NULL DEFAULT 1,
  status text NOT NULL DEFAULT 'indexed',
  pii_tags text[] NOT NULL DEFAULT ARRAY[]::text[],
  secret_tags text[] NOT NULL DEFAULT ARRAY[]::text[],
  indexed_at timestamptz,
  tombstone boolean NOT NULL DEFAULT false,
  deleted_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chunks (
  chunk_id text PRIMARY KEY,
  tenant_id text NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
  document_id text NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
  collection_id text NOT NULL REFERENCES collections(collection_id) ON DELETE CASCADE,
  modality text NOT NULL DEFAULT 'text',
  text text NOT NULL DEFAULT '',
  token_count integer NOT NULL DEFAULT 0,
  position integer NOT NULL DEFAULT 0,
  heading_path text[] NOT NULL DEFAULT ARRAY[]::text[],
  offset_mapping jsonb,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  metadata_schema_version integer NOT NULL DEFAULT 1,
  embedding_model_version text NOT NULL DEFAULT '',
  embedding vector(256),
  tombstone boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS acl_grants (
  grant_id text PRIMARY KEY,
  tenant_id text NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
  scope_type text NOT NULL CHECK (scope_type IN ('tenant', 'collection', 'document')),
  scope_id text NOT NULL,
  subject_type text NOT NULL CHECK (subject_type IN ('user', 'group', 'role')),
  subject_id text NOT NULL,
  permission text NOT NULL DEFAULT 'read',
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS audit_logs (
  log_id text PRIMARY KEY,
  tenant_id text NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
  timestamp timestamptz NOT NULL DEFAULT now(),
  request_id text,
  trace_id text,
  correlation_id text,
  actor_id text,
  actor_role text,
  actor_group text,
  app_id text,
  api_client_id text,
  actor_type text NOT NULL DEFAULT 'user',
  action text NOT NULL,
  resource_type text NOT NULL,
  resource_id text,
  decision text NOT NULL,
  reason text,
  policy_version text,
  approval_status_at_use text,
  citation_ids text[] NOT NULL DEFAULT ARRAY[]::text[],
  document_ids_used text[] NOT NULL DEFAULT ARRAY[]::text[],
  chunk_ids_used text[] NOT NULL DEFAULT ARRAY[]::text[],
  retrieval_profile_id text,
  provider_policy_id text,
  pii_redaction_applied boolean NOT NULL DEFAULT false,
  secret_redaction_applied boolean NOT NULL DEFAULT false,
  logging_policy_id text,
  raw_content_stored boolean NOT NULL DEFAULT false
);

CREATE INDEX IF NOT EXISTS idx_documents_tenant_collection_live
  ON documents (tenant_id, collection_id, tombstone, deleted_at);

CREATE INDEX IF NOT EXISTS idx_documents_tenant_source_doc
  ON documents (tenant_id, source_id, source_document_id);

CREATE INDEX IF NOT EXISTS idx_documents_metadata_hot
  ON documents (
    tenant_id,
    ((metadata->>'document_type')),
    ((metadata->>'approval_status')),
    ((metadata->>'effective_date'))
  );

CREATE INDEX IF NOT EXISTS idx_chunks_tenant_collection_live
  ON chunks (tenant_id, collection_id, tombstone);

CREATE INDEX IF NOT EXISTS idx_chunks_tenant_document_live
  ON chunks (tenant_id, document_id, tombstone);

CREATE INDEX IF NOT EXISTS idx_chunks_embedding_hnsw
  ON chunks USING hnsw (embedding vector_cosine_ops)
  WHERE embedding IS NOT NULL AND tombstone = false;

CREATE INDEX IF NOT EXISTS idx_acl_grants_lookup
  ON acl_grants (tenant_id, scope_type, scope_id, subject_type, subject_id);

CREATE INDEX IF NOT EXISTS idx_audit_logs_tenant_timestamp
  ON audit_logs (tenant_id, timestamp DESC);

ALTER TABLE tenants ENABLE ROW LEVEL SECURITY;
ALTER TABLE query_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE collections ENABLE ROW LEVEL SECURITY;
ALTER TABLE data_sources ENABLE ROW LEVEL SECURITY;
ALTER TABLE documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE acl_grants ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;

ALTER TABLE tenants FORCE ROW LEVEL SECURITY;
ALTER TABLE query_profiles FORCE ROW LEVEL SECURITY;
ALTER TABLE collections FORCE ROW LEVEL SECURITY;
ALTER TABLE data_sources FORCE ROW LEVEL SECURITY;
ALTER TABLE documents FORCE ROW LEVEL SECURITY;
ALTER TABLE chunks FORCE ROW LEVEL SECURITY;
ALTER TABLE acl_grants FORCE ROW LEVEL SECURITY;
ALTER TABLE audit_logs FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_isolation_tenants ON tenants;
DROP POLICY IF EXISTS tenant_isolation_query_profiles ON query_profiles;
DROP POLICY IF EXISTS tenant_isolation_collections ON collections;
DROP POLICY IF EXISTS tenant_isolation_data_sources ON data_sources;
DROP POLICY IF EXISTS tenant_isolation_documents ON documents;
DROP POLICY IF EXISTS tenant_isolation_chunks ON chunks;
DROP POLICY IF EXISTS tenant_isolation_acl_grants ON acl_grants;
DROP POLICY IF EXISTS tenant_isolation_audit_logs ON audit_logs;

CREATE POLICY tenant_isolation_tenants ON tenants
  USING (tenant_id = raku.current_tenant_id())
  WITH CHECK (tenant_id = raku.current_tenant_id());

CREATE POLICY tenant_isolation_query_profiles ON query_profiles
  USING (tenant_id = raku.current_tenant_id())
  WITH CHECK (tenant_id = raku.current_tenant_id());

CREATE POLICY tenant_isolation_collections ON collections
  USING (tenant_id = raku.current_tenant_id())
  WITH CHECK (tenant_id = raku.current_tenant_id());

CREATE POLICY tenant_isolation_data_sources ON data_sources
  USING (tenant_id = raku.current_tenant_id())
  WITH CHECK (tenant_id = raku.current_tenant_id());

CREATE POLICY tenant_isolation_documents ON documents
  USING (tenant_id = raku.current_tenant_id())
  WITH CHECK (tenant_id = raku.current_tenant_id());

CREATE POLICY tenant_isolation_chunks ON chunks
  USING (tenant_id = raku.current_tenant_id())
  WITH CHECK (tenant_id = raku.current_tenant_id());

CREATE POLICY tenant_isolation_acl_grants ON acl_grants
  USING (tenant_id = raku.current_tenant_id())
  WITH CHECK (tenant_id = raku.current_tenant_id());

CREATE POLICY tenant_isolation_audit_logs ON audit_logs
  USING (tenant_id = raku.current_tenant_id())
  WITH CHECK (tenant_id = raku.current_tenant_id());

GRANT USAGE ON SCHEMA public, raku TO raku_app;
GRANT SELECT, INSERT, UPDATE, DELETE
  ON tenants, query_profiles, collections, data_sources, documents, chunks, acl_grants, audit_logs
  TO raku_app;
