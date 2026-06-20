from __future__ import annotations

import unittest

from raku_rag.industry import InvestmentApiService


class InvestmentApiServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.service = InvestmentApiService()

    def test_metadata_import_and_enrich_normalize_aliases(self) -> None:
        result = self.service.metadata_import(
            "tenant_alpha",
            {
                "collection_id": "funds",
                "records": [
                    {
                        "document_id": "prospectus_001",
                        "metadata": {
                            "fund_id": "FUND-001",
                            "association_code": "A001",
                            "currency_hedge": "partial",
                            "risk_classification": "high",
                            "distributor_id": "D001",
                            "document_type": "statutory_prospectus",
                        },
                    },
                    {"document_id": "bad", "metadata": {"fund_id": 123}},
                ],
            },
        )
        self.assertEqual(result["accepted_count"], 1)
        self.assertEqual(result["rejected_count"], 1)

        enriched = self.service.enrich_document(
            "tenant_alpha",
            {
                "document_id": "monthly_report_001",
                "collection_id": "funds",
                "document_type": "monthly_report",
                "metadata": {"fund_id": "FUND-001", "association_code": "A001"},
            },
        )
        self.assertTrue(enriched["validation"]["valid"])
        self.assertEqual(enriched["investment_metadata"]["tenant_id"], "tenant_alpha")
        self.assertEqual(enriched["normalized_aliases"]["fund_code"], "A001")

    def test_fund_knowledge_is_acl_filtered(self) -> None:
        fund_view = self.service.fund_knowledge("tenant_alpha", "FUND-001", ("admin",))
        self.assertEqual(fund_view["fund_id"], "FUND-001")
        self.assertTrue(fund_view["documents"])
        self.assertTrue(fund_view["prospectus_refs"])

        restricted = self.service.fund_knowledge("tenant_alpha", "FUND-002", ("sales_support",))
        document_ids = {document["document_id"] for document in restricted["documents"]}
        self.assertNotIn("FUND-002_運用会議メモ", document_ids)
        self.assertNotIn("FUND-002_銘柄調査メモ", document_ids)

    def test_workflows_and_compliance_review_contracts(self) -> None:
        fund_answer = self.service.fund_question(
            "tenant_alpha", ("product_staff",), {"question": "信託報酬を教えて"}
        )
        self.assertEqual(fund_answer["status"], "ok")
        self.assertTrue(fund_answer["review_required"])

        advice = self.service.fund_question(
            "tenant_alpha", ("product_staff",), {"question": "この顧客に買わせるべきか"}
        )
        self.assertEqual(advice["status"], "blocked")
        self.assertTrue(advice["gate_decision"]["blocked"])

        rfp = self.service.rfp_response_draft(
            "tenant_alpha", ("product_staff",), {"question": "運用体制を説明して"}
        )
        self.assertEqual(rfp["artifact_type"], "rfp_response")
        stored = self.service.draft(rfp["artifact_id"])
        self.assertEqual(stored["created_by"], "ai")
        self.assertFalse(stored["auto_approved"])
        self.assertFalse(stored["auto_compliance_approved"])

        review = self.service.review_draft(
            rfp["artifact_id"], {"action": "approve", "reviewer_id": "reviewer_1"}
        )
        self.assertEqual(review["status"], "in_review")
        compliance = self.service.compliance_review(
            rfp["artifact_id"], {"action": "compliance_approve", "reviewer_id": "comp_1"}
        )
        self.assertEqual(compliance["compliance_review_status"], "pending")

        ddq = self.service.ddq_response_draft("tenant_alpha", ("product_staff",), {})
        inquiry = self.service.inquiry_reply_draft("tenant_alpha", ("product_staff",), {})
        monthly = self.service.monthly_commentary_draft("tenant_alpha", ("product_staff",), {})
        self.assertEqual(ddq["artifact_type"], "ddq_response")
        self.assertEqual(inquiry["artifact_type"], "inquiry_reply")
        self.assertEqual(monthly["artifact_type"], "monthly_commentary")

    def test_marketing_disclosure_dashboard_kpi_audit_and_governance(self) -> None:
        marketing = self.service.marketing_material_check(
            "tenant_alpha",
            ("product_staff",),
            {"statements": ["過去実績は将来成果を保証します"]},
        )
        self.assertEqual(marketing["artifact_type"], "marketing_material_comment")
        self.assertTrue(marketing["contradiction_results"])
        evidence = self.service.disclosure_evidence(marketing["artifact_id"])
        self.assertTrue(evidence["evidence"])

        self.service.rfp_response_draft("tenant_alpha", ("product_staff",), {})
        self.service.monthly_commentary_draft("tenant_alpha", ("product_staff",), {})

        dashboard = self.service.dashboard("tenant_alpha", ("admin",))
        widget_ids = {widget["widget_id"] for widget in dashboard["widgets"]}
        self.assertIn("regulated_query_count", widget_ids)
        self.assertIn("compliance_review_pending_count", widget_ids)

        kpi = self.service.kpi("tenant_alpha", ("admin",))
        self.assertGreaterEqual(kpi["marketing_material_check_count"], 1)
        self.assertGreaterEqual(kpi["monthly_commentary_draft_count"], 1)

        audit = self.service.audit()
        event_types = {event["event_type"] for event in audit["events"]}
        self.assertIn("investment.marketing_material_check", event_types)
        self.assertIn("investment.draft_generated", event_types)

        governance = self.service.governance_status()
        self.assertEqual(governance["poc_readiness"], "ready")
        self.assertFalse(governance["advice_boundary"]["auto_advice"])
        self.assertFalse(governance["compliance_review"]["auto_approval"])

    def test_marketing_check_is_per_statement_and_policy_driven(self) -> None:
        # GAP-F12 (FR-IM-031/034): a REAL per-statement contradiction check — different inputs produce
        # different outcomes (kills the static single-contradiction stub).
        contradicting = self.service.marketing_material_check(
            "tenant_alpha", ("product_staff",), {"statements": ["過去実績から将来成果を保証します"]}
        )
        results = contradicting["contradiction_results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["contradiction_type"], "prohibited_expression")
        self.assertEqual(results[0]["severity"], "high")
        self.assertIn("matched_source", results[0])
        self.assertIn("recommended_action", results[0])
        self.assertEqual(contradicting["status"], "review_required")
        consistent = self.service.marketing_material_check(
            "tenant_alpha", ("product_staff",), {"statements": ["信託報酬は目論見書記載の通りです"]}
        )
        self.assertEqual(consistent["contradiction_results"], [])
        self.assertEqual(consistent["status"], "ok")
        two = self.service.marketing_material_check(
            "tenant_alpha", ("product_staff",), {"statements": ["元本保証です", "必ず増えます"]}
        )
        self.assertEqual(len(two["contradiction_results"]), 2)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
