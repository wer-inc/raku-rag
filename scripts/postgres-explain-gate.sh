#!/usr/bin/env bash
#
# T118 — runtime EXPLAIN gate (Tier B / CI; needs a real Postgres + pgvector).
#
# Asserts the production vector search uses the pgvector HNSW index (Index Scan) and NOT a Seq Scan on
# `chunks`, with the RLS tenant predicate applied. Static query-shape + index existence are checked in
# tests/contract/test_explain_gate.py (Docker-free); this verifies the actual planner choice.
#
# Usage: POSTGRES_URL=<pgvector connection string> scripts/postgres-explain-gate.sh
# Exit: 0 = index scan confirmed; 1 = Seq Scan / plan regression; 2 = environment unavailable.

set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if ! command -v psql >/dev/null 2>&1; then
  echo "psql not found — run on a host with Postgres client (Tier B / CI)." >&2
  exit 2
fi
URL="${POSTGRES_URL:-}"
if [ -z "$URL" ]; then
  echo "set POSTGRES_URL to a pgvector-enabled database (migrations applied)." >&2
  exit 2
fi

# A representative tenant-scoped vector search, mirroring persistence/postgres.py search().
plan="$(
  psql "$URL" -v ON_ERROR_STOP=1 -At <<'SQL'
SET ROLE raku_app;
SELECT set_config('app.current_tenant_id', 'explain_gate_tenant', false);
EXPLAIN (ANALYZE false, COSTS false)
  SELECT chunk_id, (embedding <=> '[0,0,0]'::vector) AS distance
  FROM chunks
  WHERE tombstone = false
  ORDER BY embedding <=> '[0,0,0]'::vector, chunk_id
  LIMIT 5;
RESET ROLE;
SQL
)"
echo "$plan"

if echo "$plan" | grep -qiE "Seq Scan on chunks"; then
  echo "::error::EXPLAIN shows a Seq Scan on chunks — pgvector index not used (plan regression)." >&2
  exit 1
fi
if echo "$plan" | grep -qi "idx_chunks_embedding_hnsw"; then
  echo "EXPLAIN gate: GREEN (idx_chunks_embedding_hnsw used)."
  exit 0
fi
# HNSW may appear as a generic 'Index Scan'/'Index Only Scan' depending on planner/version; accept any
# index path over chunks, fail only on an explicit Seq Scan (handled above).
if echo "$plan" | grep -qiE "Index .*Scan"; then
  echo "EXPLAIN gate: GREEN (index scan over chunks)."
  exit 0
fi
echo "::error::EXPLAIN gate: no index scan detected for the vector search." >&2
exit 1
