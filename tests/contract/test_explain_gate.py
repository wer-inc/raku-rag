"""T118 — query-plan readiness (static half of the EXPLAIN gate).

The default gate is Docker/Postgres-free, so this statically pins the SHAPE that an ``EXPLAIN`` on a
real Postgres would confirm: the vector search ranks via pgvector cosine over the live (non-tombstoned)
set with the tenant predicate enforced by RLS, and the hot-path indexes (hnsw + metadata/identifier)
exist for index scan + filter pushdown. The runtime ``EXPLAIN`` (asserting an Index Scan, not a Seq
Scan) runs against a real Postgres via ``scripts/postgres-explain-gate.sh`` (Tier B / CI).
"""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
POSTGRES = (ROOT / "src/raku_rag/persistence/postgres.py").read_text(encoding="utf-8")
HYBRID = (ROOT / "src/raku_rag/core/hybrid_retrieval.py").read_text(encoding="utf-8")
MIGRATIONS = ROOT / "infra/db/migrations/postgres"


def _migrations_sql() -> str:
    return "\n".join(
        p.read_text(encoding="utf-8")
        for p in sorted(MIGRATIONS.glob("[0-9][0-9][0-9][0-9]_*.sql"))
        if ".down." not in p.name
    )


class ExplainGateContractTest(unittest.TestCase):
    def test_vector_search_uses_pgvector_cosine_over_live_set(self) -> None:
        # pgvector cosine distance rank (uses idx_chunks_embedding_hnsw) + live-set filter pushdown.
        self.assertIn("embedding <=> %s::vector", POSTGRES)
        self.assertIn("WHERE tombstone = false", POSTGRES)
        self.assertIn("ORDER BY embedding <=> %s::vector", POSTGRES)

    def test_tenant_predicate_is_rls_bound(self) -> None:
        # The tenant filter is enforced by RLS via the session GUC, not an ad-hoc WHERE the planner
        # could skip — set per request before the query.
        self.assertIn("set_config('app.current_tenant_id'", POSTGRES)

    def test_hot_path_indexes_declared(self) -> None:
        sql = _migrations_sql()
        self.assertIn("idx_chunks_embedding_hnsw", sql)
        self.assertIn("USING hnsw (embedding vector_cosine_ops)", sql)
        self.assertIn("WHERE embedding IS NOT NULL AND tombstone = false", sql)  # partial index
        self.assertIn("idx_chunks_text_lexical_live", sql)
        self.assertIn("USING gin (to_tsvector('simple', text))", sql)
        # metadata / identifier hot fields for exact-match filter pushdown
        self.assertIn("idx_documents_metadata_hot", sql)
        self.assertIn("idx_documents_identifier_hot_fields", sql)

    def test_core_identifier_exact_match_leg_is_deployed(self) -> None:
        self.assertIn("metadata_exact_matches", POSTGRES)
        self.assertIn("JOIN documents", POSTGRES)
        self.assertIn("HOT_IDENTIFIER_FIELDS", POSTGRES)
        self.assertIn("equipment_id", HYBRID)
        self.assertIn("alarm_code", HYBRID)

    def test_core_lexical_recency_leg_is_deployed(self) -> None:
        self.assertIn("lexical_matches", POSTGRES)
        self.assertIn("lexical_match_score", POSTGRES)
        self.assertIn("to_tsvector('simple', c.text) @@ to_tsquery('simple'", POSTGRES)
        self.assertIn("LEXICAL_RECENCY_BOOST_MAX", HYBRID)
        self.assertIn("effective_date", HYBRID)

    def test_explain_gate_script_present_for_runtime_plan_check(self) -> None:
        script = ROOT / "scripts/postgres-explain-gate.sh"
        self.assertTrue(script.exists(), "runtime EXPLAIN gate script must exist for Tier-B/CI")
        body = script.read_text(encoding="utf-8")
        self.assertIn("EXPLAIN", body)
        self.assertIn("idx_chunks_embedding_hnsw", body)
        self.assertIn("Seq Scan", body)  # the failure condition it guards against


if __name__ == "__main__":
    unittest.main()
