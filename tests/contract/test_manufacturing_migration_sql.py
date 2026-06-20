from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
UP = ROOT / "infra/db/migrations/postgres/0006_manufacturing_domain.sql"
DOWN = ROOT / "infra/db/migrations/postgres/0006_manufacturing_domain.down.sql"
MODELS = ROOT / "src/raku_rag/persistence/manufacturing_models.py"


class ManufacturingMigrationSqlTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.sql = UP.read_text(encoding="utf-8")
        cls.down = DOWN.read_text(encoding="utf-8")
        cls.models = MODELS.read_text(encoding="utf-8")

    def assertTableHas(self, table: str, *tokens: str) -> None:
        pattern = rf"CREATE TABLE IF NOT EXISTS {table} \((?P<body>.*?)\);"
        match = re.search(pattern, self.sql, re.S)
        self.assertIsNotNone(match, f"missing table {table}")
        body = match.group("body")
        for token in tokens:
            with self.subTest(table=table, token=token):
                self.assertIn(token, body)

    def test_core_entities_are_tenant_scoped(self) -> None:
        for table in (
            "manufacturing_factories",
            "manufacturing_equipment",
            "manufacturing_trouble_cases",
            "manufacturing_countermeasures",
            "manufacturing_document_metadata",
            "manufacturing_draft_artifacts",
            "manufacturing_safety_decisions",
            "manufacturing_kpi_values",
        ):
            self.assertTableHas(table, "tenant_id text NOT NULL")

    def test_metadata_acl_tombstone_and_materialization_columns_exist(self) -> None:
        self.assertTableHas(
            "manufacturing_document_metadata",
            "document_id text NOT NULL",
            "factory_id text NOT NULL DEFAULT ''",
            "department_id text NOT NULL DEFAULT ''",
            "equipment_id text",
            "approval_status text NOT NULL DEFAULT 'draft'",
            "approval_metadata_checksum text NOT NULL DEFAULT ''",
            "tombstone boolean NOT NULL DEFAULT false",
            "no_train_policy_ref text NOT NULL DEFAULT 'default_no_train'",
        )
        self.assertTableHas(
            "manufacturing_dashboard_metric_snapshots",
            "metrics jsonb NOT NULL DEFAULT '{}'::jsonb",
            "safety_telemetry jsonb NOT NULL DEFAULT '{}'::jsonb",
            "source_ingestion_run_id text NOT NULL DEFAULT ''",
            "dagster_run_id text",
            "materialized_at timestamptz NOT NULL DEFAULT now()",
        )

    def test_indexes_rls_and_grants_are_declared(self) -> None:
        for token in (
            "idx_mfg_metadata_filter",
            "idx_mfg_kpi_filter",
            "'ALTER TABLE %I ENABLE ROW LEVEL SECURITY'",
            "'ALTER TABLE %I FORCE ROW LEVEL SECURITY'",
            "tenant_id = raku.current_tenant_id()",
            "GRANT SELECT, INSERT, UPDATE, DELETE",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.sql)

    def test_optional_sqlalchemy_model_file_tracks_tables_without_required_dependency(self) -> None:
        self.assertIn("MANUFACTURING_TABLES", self.models)
        self.assertIn("ManufacturingDocumentMetadataModel", self.models)
        self.assertIn("except ModuleNotFoundError", self.models)

    def test_down_migration_drops_manufacturing_tables(self) -> None:
        for table in (
            "manufacturing_dashboard_metric_snapshots",
            "manufacturing_kpi_values",
            "manufacturing_document_metadata",
            "manufacturing_trouble_cases",
            "manufacturing_factories",
        ):
            with self.subTest(table=table):
                self.assertIn(f"DROP TABLE IF EXISTS {table}", self.down)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
