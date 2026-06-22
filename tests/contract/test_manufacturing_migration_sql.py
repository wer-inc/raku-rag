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

    def test_domain_enum_checks_are_declared(self) -> None:
        self.assertTableHas(
            "manufacturing_document_metadata",
            "document_kind text NOT NULL CHECK",
            "'work_instruction'",
            "'inspection'",
            "'quality_report'",
            "'trouble_report'",
            "'minutes'",
            "'ledger'",
            "'drawing'",
            "'training'",
            "approval_status text NOT NULL DEFAULT 'draft' CHECK",
            "approval_status IN ('draft', 'pending_review', 'approved', 'obsolete')",
            "approval_source text NOT NULL DEFAULT 'workflow' CHECK",
            "approval_source IN ('imported', 'workflow')",
        )
        self.assertTableHas(
            "manufacturing_work_instructions",
            "approval_status text NOT NULL DEFAULT 'approved' CHECK",
            "approval_status IN ('draft', 'pending_review', 'approved', 'obsolete')",
        )
        self.assertTableHas(
            "manufacturing_countermeasures",
            "type text NOT NULL DEFAULT 'candidate' CHECK",
            "type IN ('reference', 'candidate')",
            "measure_class text NOT NULL DEFAULT 'unknown' CHECK",
            "measure_class IN ('provisional', 'permanent', 'unknown')",
        )
        self.assertTableHas(
            "manufacturing_draft_artifacts",
            "artifact_type text NOT NULL CHECK",
            "artifact_type IN ('checklist', 'trouble_report', 'quality_report', 'training', 'faq')",
            "status text NOT NULL DEFAULT 'draft' CHECK",
            "status IN ('draft', 'in_review', 'approved', 'rejected', 'archived')",
            "created_by text NOT NULL DEFAULT 'ai' CHECK",
            "created_by IN ('ai', 'user')",
        )
        self.assertTableHas(
            "manufacturing_safety_decisions",
            "classification_source text NOT NULL DEFAULT '' CHECK",
            "classification_source IN ('', 'metadata', 'rule', 'keyword', 'llm')",
            "safety_block_reason text CHECK",
            "safety_block_reason IN ('approved_citation_missing', 'insufficient_evidence', 'other_block')",
        )
        self.assertTableHas(
            "manufacturing_audit_events",
            "safety_block_reason text CHECK",
            "safety_block_reason IN ('approved_citation_missing', 'insufficient_evidence', 'other_block')",
        )

    def test_ai_generated_drafts_cannot_be_approved_by_database_constraint(self) -> None:
        self.assertTableHas(
            "manufacturing_draft_artifacts",
            "CHECK (NOT (created_by = 'ai' AND status = 'approved'))",
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
