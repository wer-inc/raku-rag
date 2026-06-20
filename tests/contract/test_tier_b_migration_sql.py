"""Tier B bootstrap SQL contract.

These checks are intentionally static so the default stdlib gate stays Docker-free. The actual
Postgres execution lives behind ``scripts/gate.sh b``.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
UP = ROOT / "infra/db/migrations/postgres/0001_core_rls.sql"
DOWN = ROOT / "infra/db/migrations/postgres/0001_core_rls.down.sql"


class TierBMigrationSqlTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.sql = UP.read_text(encoding="utf-8")
        cls.down = DOWN.read_text(encoding="utf-8")

    def test_core_tables_are_tenant_scoped(self) -> None:
        for table in (
            "tenants",
            "collections",
            "data_sources",
            "documents",
            "chunks",
            "acl_grants",
            "audit_logs",
            "query_profiles",
        ):
            with self.subTest(table=table):
                pattern = rf"CREATE TABLE IF NOT EXISTS {table} \((?P<body>.*?)\);"
                match = re.search(pattern, self.sql, re.S)
                self.assertIsNotNone(match, f"missing table {table}")
                self.assertIn("tenant_id", match.group("body"))

    def test_pgvector_and_live_retrieval_indexes_exist(self) -> None:
        self.assertIn("CREATE EXTENSION IF NOT EXISTS vector", self.sql)
        self.assertIn("embedding vector(256)", self.sql)
        self.assertIn("USING hnsw (embedding vector_cosine_ops)", self.sql)
        self.assertIn("tombstone = false", self.sql)
        self.assertIn("idx_documents_tenant_collection_live", self.sql)
        self.assertIn("idx_chunks_tenant_collection_live", self.sql)

    def test_rls_is_forced_and_bound_to_session_tenant(self) -> None:
        for table in (
            "tenants",
            "collections",
            "data_sources",
            "documents",
            "chunks",
            "acl_grants",
            "audit_logs",
            "query_profiles",
        ):
            with self.subTest(table=table):
                self.assertIn(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY", self.sql)
                self.assertIn(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY", self.sql)
        self.assertIn("current_setting('app.current_tenant_id', true)", self.sql)
        self.assertIn("tenant_id = raku.current_tenant_id()", self.sql)
        self.assertIn("CREATE ROLE raku_app NOLOGIN", self.sql)
        self.assertNotIn("BYPASSRLS", self.sql.upper())

    def test_policy_lifecycle_and_logging_defaults_are_present(self) -> None:
        for field in ("profile_version", "schema_version", "effective_from", "deprecated_at"):
            self.assertIn(field, self.sql)
        self.assertIn("metadata_schema_version integer NOT NULL DEFAULT 1", self.sql)
        self.assertIn("raw_content_stored boolean NOT NULL DEFAULT false", self.sql)

    def test_down_migration_drops_core_objects(self) -> None:
        for name in ("chunks", "documents", "collections", "tenants", "raku.current_tenant_id"):
            self.assertIn(name, self.down)
        self.assertNotIn("DROP ROLE", self.down.upper())


if __name__ == "__main__":
    unittest.main()
