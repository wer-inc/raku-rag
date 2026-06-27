"""Schema lock contract for T008/T091.

The default gate is Docker-free, so these checks statically guard the PostgreSQL migrations that
Tier B applies in Docker-backed environments.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = ROOT / "infra/db/migrations/postgres"


def up_sql() -> str:
    parts = []
    for path in sorted(MIGRATIONS.glob("[0-9][0-9][0-9][0-9]_*.sql")):
        if ".down." not in path.name:
            parts.append(path.read_text(encoding="utf-8"))
    return "\n".join(parts)


class SchemaLockMigrationSqlTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.sql = up_sql()

    def assertTableHas(self, table: str, *tokens: str) -> None:
        pattern = rf"CREATE TABLE IF NOT EXISTS {table} \((?P<body>.*?)\);"
        match = re.search(pattern, self.sql, re.S)
        self.assertIsNotNone(match, f"missing table {table}")
        body = match.group("body")
        for token in tokens:
            with self.subTest(table=table, token=token):
                self.assertIn(token, body)

    def test_schema_lock_tables_are_tenant_scoped(self) -> None:
        for table in (
            "visual_assets",
            "layout_regions",
            "crops",
            "embeddings",
            "cost_records",
            "budgets",
            "source_document_manifests",
            "asset_materialization_refs",
            "reindex_plans",
            "provider_policies",
            "retrieval_profiles",
            "logging_policies",
            "embedding_jobs",
            "rerank_traces",
            "provider_config_audit_events",
            "evaluation_runs",
        ):
            self.assertTableHas(table, "tenant_id text NOT NULL")

    def test_evaluation_run_persistence_columns_present(self) -> None:
        # 0007 (P2-9): full eval-run persistence is an additive ALTER (not in the CREATE TABLE body),
        # so assert against the concatenated SQL. These columns let runs be trended across releases.
        for column in (
            "eval_set_id text",
            "baseline boolean NOT NULL DEFAULT false",
            "gate_result text NOT NULL DEFAULT 'passed'",
            "baseline_comparison jsonb NOT NULL DEFAULT '{}'::jsonb",
            "probe_results jsonb NOT NULL DEFAULT '[]'::jsonb",
            "probes_executed boolean NOT NULL DEFAULT false",
            "version_registry jsonb NOT NULL DEFAULT '{}'::jsonb",
        ):
            with self.subTest(column=column):
                self.assertIn(column, self.sql)
        self.assertIn("idx_evaluation_runs_trend", self.sql)
        # the additive ALTER must target the existing evaluation_runs table (created in 0002)
        self.assertIn("ALTER TABLE evaluation_runs", self.sql)

    def test_evaluation_run_persistence_has_down_migration(self) -> None:
        down = (MIGRATIONS / "0007_eval_run_persistence.down.sql").read_text(encoding="utf-8")
        self.assertIn("DROP INDEX IF EXISTS idx_evaluation_runs_trend", down)
        for column in (
            "probes_executed",
            "probe_results",
            "baseline_comparison",
            "gate_result",
            "baseline",
            "eval_set_id",
        ):
            with self.subTest(column=column):
                self.assertIn(f"DROP COLUMN IF EXISTS {column}", down)

    def test_datasource_sync_runtime_is_tenant_scoped(self) -> None:
        datasource_sync = (MIGRATIONS / "0013_datasource_sync_runtime.sql").read_text(
            encoding="utf-8"
        )
        datasource_sync_down = (MIGRATIONS / "0013_datasource_sync_runtime.down.sql").read_text(
            encoding="utf-8"
        )
        self.assertIn("PRIMARY KEY (tenant_id, source_id)", datasource_sync)
        self.assertIn("idx_data_sources_tenant_collection_status", datasource_sync)
        self.assertIn("partially_succeeded", datasource_sync)
        self.assertIn("source_sync_states_status_check", datasource_sync_down)

    def test_visual_understanding_async_state_and_indexes_have_down_migration(self) -> None:
        visual = (MIGRATIONS / "0014_visual_understanding.sql").read_text(encoding="utf-8")
        visual_down = (MIGRATIONS / "0014_visual_understanding.down.sql").read_text(
            encoding="utf-8"
        )

        for token in (
            "async_provider",
            "async_job_id",
            "async_job_status",
            "extractor_version",
            "idx_layout_regions_structured",
            "idx_chunks_structured_kind",
            "idx_chunks_structured_parent",
            "PRIMARY KEY (tenant_id, source_id)",
        ):
            with self.subTest(token=token):
                self.assertIn(token, visual)
        for token in (
            "DROP INDEX IF EXISTS idx_chunks_structured_parent",
            "DROP INDEX IF EXISTS idx_chunks_structured_kind",
            "DROP INDEX IF EXISTS idx_layout_regions_structured",
            "DROP COLUMN IF EXISTS extractor_version",
            "DROP COLUMN IF EXISTS async_job_status",
            "DROP COLUMN IF EXISTS async_job_id",
            "DROP COLUMN IF EXISTS async_provider",
        ):
            with self.subTest(token=token):
                self.assertIn(token, visual_down)

    def test_visual_provider_policy_columns_have_down_migration(self) -> None:
        visual_policy = (MIGRATIONS / "0015_visual_provider_policy.sql").read_text(
            encoding="utf-8"
        )
        visual_policy_down = (
            MIGRATIONS / "0015_visual_provider_policy.down.sql"
        ).read_text(encoding="utf-8")

        for token in (
            "allowed_layout_providers",
            "allowed_structured_providers",
            "allowed_visual_embedding_providers",
            "allowed_vlm_providers",
            "allowed_caption_providers",
            "opt_in_status_by_family",
        ):
            with self.subTest(token=token):
                self.assertIn(token, visual_policy)
                self.assertIn(f"DROP COLUMN IF EXISTS {token}", visual_policy_down)

    def test_evaluation_run_version_registry_has_down_migration(self) -> None:
        down = (MIGRATIONS / "0011_eval_version_registry.down.sql").read_text(encoding="utf-8")
        self.assertIn("DROP COLUMN IF EXISTS version_registry", down)

    def test_visual_and_metadata_schema_versions_are_present(self) -> None:
        for table in ("documents", "chunks", "visual_assets", "layout_regions"):
            self.assertTableHas(
                table, "metadata jsonb", "metadata_schema_version integer NOT NULL DEFAULT 1"
            )
        self.assertTableHas("layout_regions", "generated_caption_text text NOT NULL DEFAULT ''")
        self.assertTableHas("crops", "redaction_policy_ref text NOT NULL DEFAULT 'inherit'")

    def test_policy_lifecycle_fields_are_present(self) -> None:
        for table in (
            "query_profiles",
            "provider_policies",
            "retrieval_profiles",
            "logging_policies",
        ):
            self.assertTableHas(
                table,
                "profile_version",
                "schema_version integer NOT NULL DEFAULT 1",
                "effective_from",
                "deprecated_at",
            )

    def test_embedding_and_retrieval_indexes_are_declared(self) -> None:
        self.assertIn("target_type text NOT NULL CHECK", self.sql)
        self.assertIn("modality text NOT NULL CHECK", self.sql)
        self.assertIn("embedding vector(1024)", self.sql)
        self.assertIn("idx_embeddings_hnsw", self.sql)
        self.assertIn("WHERE embedding IS NOT NULL AND tombstone = false", self.sql)
        self.assertIn("idx_chunks_text_lexical_live", self.sql)
        self.assertIn("to_tsvector('simple', text)", self.sql)
        self.assertIn("idx_documents_identifier_hot_fields", self.sql)
        for field in (
            "equipment_id",
            "alarm_code",
            "property_id",
            "room_number",
            "contract_id",
            "fund_id",
            "isin",
            "invoice_id",
        ):
            self.assertIn(f"metadata->>'{field}'", self.sql)

    def test_policy_audit_and_job_tables_exist(self) -> None:
        self.assertTableHas(
            "provider_config_audit_events", "redacted_before jsonb", "redacted_after jsonb"
        )
        self.assertIn("ALTER TABLE manufacturing_audit_events", self.sql)
        self.assertIn("entry_payload jsonb NOT NULL DEFAULT '{}'::jsonb", self.sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS manufacturing_data_use_policies", self.sql)
        self.assertIn("training_opt_in boolean NOT NULL DEFAULT false", self.sql)
        self.assertIn("opt_in_contract_ref text", self.sql)
        self.assertIn("manufacturing_data_use_policies_tenant_isolation", self.sql)
        self.assertTableHas(
            "embedding_jobs", "provider_policy_id text", "retrieval_profile_id text"
        )
        self.assertTableHas(
            "rerank_traces", "candidate_count integer", "final_context_count integer"
        )
        self.assertTableHas(
            "reindex_plans", "scope jsonb", "status text NOT NULL DEFAULT 'planned'"
        )


if __name__ == "__main__":
    unittest.main()
