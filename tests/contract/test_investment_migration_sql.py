from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
UP = ROOT / "infra/db/migrations/postgres/0005_investment_domain.sql"
DOWN = ROOT / "infra/db/migrations/postgres/0005_investment_domain.down.sql"


class InvestmentMigrationSqlTest(unittest.TestCase):
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

    def test_core_investment_entities_are_tenant_scoped(self) -> None:
        for table in (
            "investment_funds",
            "investment_fund_share_classes",
            "investment_distribution_partners",
            "investment_fund_documents",
            "investment_prospectuses",
            "investment_fund_reports",
            "investment_monthly_reports",
            "investment_marketing_materials",
            "investment_guidelines",
            "investment_compliance_rules",
            "investment_rfps",
            "investment_ddqs",
            "investment_inquiry_cases",
            "investment_research_memos",
            "investment_risk_reports",
            "investment_esg_documents",
        ):
            self.assertTableHas(table, "tenant_id text NOT NULL")

    def test_metadata_acl_alias_risk_draft_and_kpi_columns_exist(self) -> None:
        self.assertTableHas(
            "investment_document_metadata",
            "fund_id text",
            "fund_code text",
            "association_code text",
            "currency_hedge_policy text",
            "currency_hedge text",
            "risk_category text",
            "risk_classification text",
            "distribution_partner_id text",
            "distributor_id text",
            "document_type text NOT NULL",
            "approval_status text NOT NULL DEFAULT 'approved'",
            "confidential_data_category text",
            "personal_data_category text",
            "regulated_activity_category text",
            "retention_policy_ref text NOT NULL DEFAULT 'investment_regulated_retention'",
        )
        self.assertTableHas(
            "investment_draft_reviews",
            "review_state text NOT NULL DEFAULT 'in_review'",
            "approval_decision text NOT NULL DEFAULT ''",
        )
        self.assertTableHas(
            "investment_compliance_reviews",
            "review_state text NOT NULL DEFAULT 'pending'",
            "required_changes text[] NOT NULL DEFAULT ARRAY[]::text[]",
            "decision text NOT NULL DEFAULT ''",
        )
        self.assertTableHas(
            "investment_disclosure_evidence",
            "source_document_ids text[] NOT NULL DEFAULT ARRAY[]::text[]",
            "contradiction_results jsonb NOT NULL DEFAULT '[]'::jsonb",
        )
        self.assertTableHas(
            "investment_risk_decisions",
            "advice_boundary_triggered boolean NOT NULL DEFAULT false",
            "regulated_activity_triggered boolean NOT NULL DEFAULT false",
            "compliance_review_required boolean NOT NULL DEFAULT true",
        )
        self.assertTableHas(
            "investment_kpi_values",
            "fund_id text",
            "department_id text",
            "regulated_activity_category text",
            "metric_name text NOT NULL",
        )

    def test_acl_filter_indexes_and_rls_are_declared(self) -> None:
        self.assertIn("idx_im_metadata_filter", self.sql)
        self.assertIn("idx_im_funds_tenant_code", self.sql)
        self.assertIn("'ALTER TABLE %I ENABLE ROW LEVEL SECURITY'", self.sql)
        self.assertIn("'ALTER TABLE %I FORCE ROW LEVEL SECURITY'", self.sql)
        self.assertIn("tenant_id = raku.current_tenant_id()", self.sql)
        self.assertIn("GRANT SELECT, INSERT, UPDATE, DELETE", self.sql)

    def test_down_migration_drops_investment_tables(self) -> None:
        for table in (
            "investment_kpi_values",
            "investment_document_metadata",
            "investment_compliance_reviews",
            "investment_fund_documents",
            "investment_funds",
        ):
            with self.subTest(table=table):
                self.assertIn(f"DROP TABLE IF EXISTS {table}", self.down)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
