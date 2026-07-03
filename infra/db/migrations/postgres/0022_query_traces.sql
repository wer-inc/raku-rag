-- ★G1: query_traces — durable per-query hot-path trace (goal.md §2-5 observability).
--
-- The answer path already measures stage latency / token counts / status per request
-- (RagHotPathMetric) but kept them in-memory only, so a past production query could not be
-- reconstructed or analyzed. This table persists that record. Reference-only posture: identities
-- are hashed and NO raw query/answer/context text is stored (same stance as audit_logs).
SET search_path TO public;

CREATE TABLE IF NOT EXISTS query_traces (
  query_trace_id text PRIMARY KEY,
  tenant_id text NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
  request_id text NOT NULL DEFAULT '',
  user_id_hash text NOT NULL DEFAULT '',
  profile_id text NOT NULL DEFAULT '',
  status text NOT NULL DEFAULT '',
  model text NOT NULL DEFAULT '',
  prompt_version text NOT NULL DEFAULT '',
  llm_call_count integer NOT NULL DEFAULT 0,
  retrieval_ms numeric NOT NULL DEFAULT 0,
  rerank_ms numeric NOT NULL DEFAULT 0,
  generation_ms numeric NOT NULL DEFAULT 0,
  total_ms numeric NOT NULL DEFAULT 0,
  retrieved_chunks integer NOT NULL DEFAULT 0,
  rerank_input_count integer NOT NULL DEFAULT 0,
  context_tokens integer NOT NULL DEFAULT 0,
  prompt_tokens integer NOT NULL DEFAULT 0,
  completion_tokens integer NOT NULL DEFAULT 0,
  cache_hit boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_query_traces_tenant_created
  ON query_traces (tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_query_traces_tenant_request
  ON query_traces (tenant_id, request_id);
CREATE INDEX IF NOT EXISTS idx_query_traces_tenant_status
  ON query_traces (tenant_id, status);

ALTER TABLE query_traces ENABLE ROW LEVEL SECURITY;
ALTER TABLE query_traces FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_isolation_query_traces ON query_traces;
CREATE POLICY tenant_isolation_query_traces
  ON query_traces
  USING (tenant_id = raku.current_tenant_id())
  WITH CHECK (tenant_id = raku.current_tenant_id());

GRANT SELECT, INSERT ON query_traces TO raku_app;
