from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
UP = ROOT / "infra/db/migrations/postgres/0003_industry_framework.sql"
DOWN = ROOT / "infra/db/migrations/postgres/0003_industry_framework.down.sql"


class IndustryFrameworkMigrationSqlTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.sql = UP.read_text(encoding="utf-8")
        cls.down = DOWN.read_text(encoding="utf-8")

    def assertTableHas(self, table: str, *tokens: str) -> None:
        pattern = rf"CREATE TABLE IF NOT EXISTS {table} \((?P<body>.*?)\);"
        match = re.search(pattern, self.sql, re.S)
        self.assertIsNotNone(match, f"missing table {table}")
        body = match.group("body")
        for token in tokens:
            with self.subTest(table=table, token=token):
                self.assertIn(token, body)

    def test_010_tables_are_tenant_scoped(self) -> None:
        for table in (
            "industry_profiles",
            "metadata_schemas",
            "document_type_definitions",
            "entity_type_definitions",
            "workflow_definitions",
            "risk_policies",
            "risk_decisions",
            "required_evidence_policies",
            "approval_policies",
            "acl_mapping_policies",
            "draft_artifact_type_definitions",
            "draft_review_policies",
            "draft_artifacts",
            "kpi_definitions",
            "kpi_values",
            "dashboard_widget_definitions",
            "governance_profiles",
            "audit_event_definitions",
            "evaluation_profiles",
            "no_train_policies",
            "document_metadata_extensions",
        ):
            self.assertTableHas(table, "tenant_id text NOT NULL")

    def test_profile_schema_policy_and_draft_contract_columns_exist(self) -> None:
        self.assertTableHas(
            "industry_profiles",
            "industry_id text NOT NULL",
            "schema_version integer NOT NULL DEFAULT 1",
            "profile_version integer NOT NULL DEFAULT 1",
        )
        self.assertTableHas(
            "metadata_schemas",
            "required_fields text[]",
            "indexed_fields text[]",
            "pii_fields text[]",
        )
        self.assertTableHas(
            "risk_policies",
            "keyword_rules jsonb",
            "uncertain_case_action text NOT NULL DEFAULT 'review_required'",
        )
        self.assertTableHas(
            "required_evidence_policies",
            "required_approval_status text NOT NULL DEFAULT 'approved'",
            "require_effective_date_valid boolean NOT NULL DEFAULT true",
            "minimum_citation_count integer NOT NULL DEFAULT 1",
        )
        self.assertTableHas(
            "draft_artifacts",
            "status text NOT NULL DEFAULT 'draft'",
            "created_by text NOT NULL DEFAULT 'ai'",
            "CHECK (NOT (created_by = 'ai' AND status = 'approved'))",
        )

    def test_rls_and_shared_system_profiles_are_declared(self) -> None:
        self.assertIn("tenant_id = raku.current_tenant_id() OR tenant_id = 'system'", self.sql)
        self.assertIn("'ALTER TABLE %I ENABLE ROW LEVEL SECURITY'", self.sql)
        self.assertIn("'ALTER TABLE %I FORCE ROW LEVEL SECURITY'", self.sql)
        for table in ("industry_profiles", "metadata_schemas", "draft_artifacts"):
            with self.subTest(table=table):
                self.assertIn(f"'{table}'", self.sql)
        self.assertIn("GRANT SELECT, INSERT, UPDATE, DELETE", self.sql)

    def test_down_migration_drops_framework_tables(self) -> None:
        for table in (
            "document_metadata_extensions",
            "draft_artifacts",
            "required_evidence_policies",
            "risk_policies",
            "metadata_schemas",
            "industry_profiles",
        ):
            with self.subTest(table=table):
                self.assertIn(f"DROP TABLE IF EXISTS {table}", self.down)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
