-- 0026 — search-path performance: lexical candidate pool column (Wave 1d).
--
-- docs/product/scale-bench.md §根本原因: the lexical retrieval leg transferred the whole tenant
-- live set to Python and scored it there, O(N) per query. tsvector (0008) cannot express the
-- CJK-bigram token semantics of the shared scorer, and any "could score > 0" predicate matches
-- ~94% of a shared-vocabulary manufacturing corpus — so the narrowing key is instead the scorer's
-- own dominant component: the DISTINCT directly-matched query-term count. Ingest precomputes each
-- chunk's retrieval-token set as stable 32-bit hashes (core/hybrid_retrieval.lexical_token_hashes,
-- crc32 — computed in Python on BOTH the write and read side; Postgres only compares integers),
-- and the leg fetches only the top max(top_k*50, 1000) candidates by
-- ORDER BY icount(lexical_token_hashes & query_term_hashes) DESC (intarray), with ACL-safe
-- exhaustive fallbacks in persistence/postgres.py::lexical_matches.
--
-- The vector leg's fix (HNSW over-fetch window) needs no schema change: the 0001
-- idx_chunks_embedding_hnsw index serves it once the query shape matches its partial predicate.

-- WITH SCHEMA public: the migration session's search_path starts with "$user", which would land
-- the operators in a user schema that the runtime's SET ROLE raku_app session cannot resolve
-- ("$user" then means the roleless raku_app schema). The DO block relocates a pre-existing
-- install for the same reason (ALTER EXTENSION is valid — intarray is relocatable).
CREATE EXTENSION IF NOT EXISTS intarray WITH SCHEMA public;
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_extension e JOIN pg_namespace n ON n.oid = e.extnamespace
             WHERE e.extname = 'intarray' AND n.nspname <> 'public') THEN
    ALTER EXTENSION intarray SET SCHEMA public;
  END IF;
END $$;

ALTER TABLE chunks
  ADD COLUMN IF NOT EXISTS lexical_token_hashes integer[] NOT NULL DEFAULT '{}';

-- Candidacy pushdown (lexical_token_hashes && candidate_hashes) for selective queries.
CREATE INDEX IF NOT EXISTS idx_chunks_lexical_token_hashes_live
  ON chunks USING gin (lexical_token_hashes gin__int_ops)
  WHERE tombstone = false;

-- Un-backfilled sentinel: rows written before this migration (or by out-of-band SQL) have the
-- '{}' default and CANNOT be pool-ranked; lexical_matches probes this cheaply per query and falls
-- back to the exhaustive exact path while any such live row exists. The partial index keeps the
-- probe O(1) on fully-backfilled databases (index is empty). Backfill:
-- scripts/backfill_lexical_token_hashes.py (or re-ingest).
CREATE INDEX IF NOT EXISTS idx_chunks_lexical_tokens_unbackfilled
  ON chunks (tenant_id)
  WHERE lexical_token_hashes = '{}' AND tombstone = false AND text <> '';

-- ---------------------------------------------------------------------------------------------
-- Metadata-exact leg: precomputed hot-identifier compacts (same Wave 1d measurement: the leg's
-- 40-expression lower()/regexp_replace OR-predicate costs ~1.4s/query at N=10,000 chunks). Ingest
-- computes compact canonical identifier forms (core/hybrid_retrieval.
-- metadata_hot_identifier_compacts — provably the SAME predicate as the expression forest, not a
-- superset) for chunk AND document metadata; the leg then matches with a plain array overlap.
-- DEFAULT NULL ≠ '{}' keeps "not yet computed" (pre-0026 rows → probe → exact slow-path fallback)
-- distinct from "computed, no identifiers" ('{}').
ALTER TABLE chunks
  ADD COLUMN IF NOT EXISTS identifier_compacts text[];
ALTER TABLE documents
  ADD COLUMN IF NOT EXISTS identifier_compacts text[];

CREATE INDEX IF NOT EXISTS idx_chunks_identifier_compacts_live
  ON chunks USING gin (identifier_compacts)
  WHERE tombstone = false;
CREATE INDEX IF NOT EXISTS idx_documents_identifier_compacts_live
  ON documents USING gin (identifier_compacts)
  WHERE tombstone = false;

-- O(1) un-backfilled probes (empty once every live row is computed).
CREATE INDEX IF NOT EXISTS idx_chunks_identifier_compacts_unbackfilled
  ON chunks (tenant_id)
  WHERE identifier_compacts IS NULL AND tombstone = false;
CREATE INDEX IF NOT EXISTS idx_documents_identifier_compacts_unbackfilled
  ON documents (tenant_id)
  WHERE identifier_compacts IS NULL AND tombstone = false;
