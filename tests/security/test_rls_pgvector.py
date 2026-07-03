"""Security hard gate for Postgres RLS/pgvector schema posture.

Docker-backed execution is covered by Tier B when Docker is available; these checks keep the default
stdlib gate strict by verifying RLS intent statically and tenant isolation behavior in the in-memory
parity implementation.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from raku_rag.domain.models import ScopeType, SubjectType
from tests.helpers import claims, fresh

ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = ROOT / "infra/db/migrations/postgres"


def up_sql() -> str:
    parts = []
    for path in sorted(MIGRATIONS.glob("[0-9][0-9][0-9][0-9]_*.sql")):
        if ".down." not in path.name:
            parts.append(path.read_text(encoding="utf-8"))
    return "\n".join(parts)


class RlsPgvectorSecurityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.sql = up_sql()

    def test_retrievable_and_control_plane_tables_force_rls(self) -> None:
        for table in (
            "documents",
            "chunks",
            "visual_assets",
            "layout_regions",
            "crops",
            "embeddings",
            "ingestion_runs",
            "document_processing_states",
            "reindex_plans",
            "provider_policies",
            "retrieval_profiles",
            "logging_policies",
            "evaluation_runs",
            "query_traces",
        ):
            with self.subTest(table=table):
                self.assertIn(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY", self.sql)
                self.assertIn(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY", self.sql)
                self.assertIn(f"CREATE POLICY tenant_isolation_{table}", self.sql)

    def test_rls_is_bound_to_session_tenant_and_has_no_bypass_role(self) -> None:
        self.assertIn("current_setting('app.current_tenant_id', true)", self.sql)
        self.assertIn("tenant_id = raku.current_tenant_id()", self.sql)
        self.assertIn("CREATE ROLE raku_app NOLOGIN", self.sql)
        self.assertNotIn("BYPASSRLS", self.sql.upper())

    def test_pgvector_indexes_exclude_tombstoned_rows(self) -> None:
        self.assertIn("USING hnsw (embedding vector_cosine_ops)", self.sql)
        self.assertIn("WHERE embedding IS NOT NULL AND tombstone = false", self.sql)
        self.assertIn("idx_chunks_embedding_hnsw", self.sql)
        self.assertIn("idx_embeddings_hnsw", self.sql)

    def test_cross_tenant_vector_search_returns_zero_for_other_tenant(self) -> None:
        system = fresh()
        system.ingest_text(
            tenant_id="tenant_a",
            collection_id="manuals",
            document_id="doc_a",
            text="Pump P-12 alarm E-152 belongs to tenant A.",
        )
        system.ingest_text(
            tenant_id="tenant_b",
            collection_id="manuals",
            document_id="doc_b",
            text="Pump P-12 alarm E-152 belongs to tenant B.",
        )
        system.grant("tenant_a", ScopeType.COLLECTION, "manuals", SubjectType.USER, "alice")

        results = system.search(claims("tenant_a", "alice"), "Pump P-12 alarm E-152")

        self.assertGreaterEqual(len(results), 1)
        self.assertTrue(all(result.chunk.tenant_id == "tenant_a" for result in results))
        self.assertTrue(all(result.chunk.document_id != "doc_b" for result in results))
        self.assertEqual(system.store.last_prefiltered_count, 1)

    def test_worker_admin_reindex_and_eval_tables_require_tenant_context(self) -> None:
        for table in (
            "ingestion_runs",
            "document_processing_states",
            "reindex_plans",
            "evaluation_runs",
        ):
            with self.subTest(table=table):
                self.assertIn(f"CREATE TABLE IF NOT EXISTS {table}", self.sql)
                self.assertIn(f"CREATE POLICY tenant_isolation_{table}", self.sql)
                self.assertIn("WITH CHECK (tenant_id = raku.current_tenant_id())", self.sql)


if __name__ == "__main__":
    unittest.main()
