-- 0027 — ADR-018 extraction quarantine store.
--
-- review_required / rejected / draft_visual chunks must not live in the primary retrieval index.
-- This table preserves the chunk payload and embedding for reviewer approval while keeping
-- pgvector search, lexical search, and direct primary-index scans scoped to `chunks`.

SET search_path TO public;

CREATE TABLE IF NOT EXISTS extraction_quarantine_chunks (
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

CREATE INDEX IF NOT EXISTS idx_extraction_quarantine_tenant_document
  ON extraction_quarantine_chunks (tenant_id, document_id, tombstone);

CREATE INDEX IF NOT EXISTS idx_extraction_quarantine_review_status
  ON extraction_quarantine_chunks (
    tenant_id,
    ((metadata->>'extraction_quality_status'))
  )
  WHERE tombstone = false;

ALTER TABLE extraction_quarantine_chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE extraction_quarantine_chunks FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_isolation_extraction_quarantine_chunks
  ON extraction_quarantine_chunks;
CREATE POLICY tenant_isolation_extraction_quarantine_chunks
  ON extraction_quarantine_chunks
  USING (tenant_id = raku.current_tenant_id())
  WITH CHECK (tenant_id = raku.current_tenant_id());

GRANT SELECT, INSERT, UPDATE, DELETE
  ON extraction_quarantine_chunks
  TO raku_app;
