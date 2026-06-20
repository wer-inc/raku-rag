from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
UP = ROOT / "infra/db/migrations/postgres/0004_real_estate_domain.sql"
DOWN = ROOT / "infra/db/migrations/postgres/0004_real_estate_domain.down.sql"


class RealEstateMigrationSqlTest(unittest.TestCase):
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

    def test_core_real_estate_entities_are_tenant_scoped(self) -> None:
        for table in (
            "real_estate_properties",
            "real_estate_buildings",
            "real_estate_units",
            "real_estate_owners",
            "real_estate_occupants",
            "real_estate_lease_contracts",
            "real_estate_repair_cases",
            "real_estate_inquiry_cases",
            "real_estate_owner_reports",
        ):
            self.assertTableHas(table, "tenant_id text NOT NULL")

    def test_metadata_acl_risk_draft_and_kpi_columns_exist(self) -> None:
        self.assertTableHas(
            "real_estate_document_metadata",
            "property_id text",
            "unit_id text",
            "owner_id text",
            "document_type text NOT NULL",
            "approval_status text NOT NULL DEFAULT 'approved'",
            "personal_data_category text",
            "branch_id text",
            "no_train_policy_ref text NOT NULL DEFAULT 'default_no_train'",
            "retention_policy_ref text NOT NULL DEFAULT 'real_estate_pm_retention'",
        )
        self.assertTableHas(
            "real_estate_draft_reviews",
            "reviewer_id text",
            "reviewer_group text",
            "review_comment text NOT NULL DEFAULT ''",
            "approval_decision text NOT NULL DEFAULT ''",
        )
        self.assertTableHas(
            "real_estate_risk_decisions",
            "is_high_risk boolean NOT NULL",
            "risk_categories text[] NOT NULL DEFAULT ARRAY[]::text[]",
            "classification_source text NOT NULL DEFAULT '010_risk_policy'",
        )
        self.assertTableHas(
            "real_estate_gate_decisions",
            "approved_effective_citation_present boolean NOT NULL DEFAULT false",
            "review_required boolean NOT NULL DEFAULT true",
            "source_citation_ids text[] NOT NULL DEFAULT ARRAY[]::text[]",
        )
        self.assertTableHas(
            "real_estate_kpi_values",
            "metric_name text NOT NULL",
            "metric_value numeric(14,4) NOT NULL DEFAULT 0",
            "source_audit_log_range text NOT NULL DEFAULT ''",
        )

    def test_acl_filter_indexes_and_rls_are_declared(self) -> None:
        self.assertIn("idx_re_metadata_filter", self.sql)
        self.assertIn("idx_re_properties_tenant_branch", self.sql)
        self.assertIn("'ALTER TABLE %I ENABLE ROW LEVEL SECURITY'", self.sql)
        self.assertIn("'ALTER TABLE %I FORCE ROW LEVEL SECURITY'", self.sql)
        self.assertIn("tenant_id = raku.current_tenant_id()", self.sql)
        self.assertIn("GRANT SELECT, INSERT, UPDATE, DELETE", self.sql)

    def test_down_migration_drops_real_estate_tables(self) -> None:
        for table in (
            "real_estate_kpi_values",
            "real_estate_document_metadata",
            "real_estate_repair_cases",
            "real_estate_units",
            "real_estate_properties",
        ):
            with self.subTest(table=table):
                self.assertIn(f"DROP TABLE IF EXISTS {table}", self.down)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
