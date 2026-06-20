from __future__ import annotations

import unittest

from raku_rag.industry import RealEstateApiService


class RealEstateApiServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.service = RealEstateApiService()

    def test_metadata_import_and_enrich_validate_real_estate_fields(self) -> None:
        result = self.service.metadata_import(
            "tenant_alpha",
            {
                "collection_id": "leases",
                "records": [
                    {
                        "document_id": "lease_305",
                        "metadata": {
                            "property_id": "P001",
                            "unit_id": "U305",
                            "document_type": "lease_contract",
                        },
                    },
                    {"document_id": "bad", "metadata": {"property_id": 123}},
                ],
            },
        )
        self.assertEqual(result["accepted_count"], 1)
        self.assertEqual(result["rejected_count"], 1)

        enriched = self.service.enrich_document(
            "tenant_alpha",
            {
                "document_id": "repair_history",
                "collection_id": "repairs",
                "document_type": "repair_history",
                "metadata": {"property_id": "P001", "unit_id": "U305"},
            },
        )
        self.assertTrue(enriched["validation"]["valid"])
        self.assertEqual(enriched["real_estate_metadata"]["tenant_id"], "tenant_alpha")
        self.assertEqual(enriched["warnings"], [])

    def test_property_and_unit_knowledge_are_acl_filtered(self) -> None:
        property_view = self.service.property_knowledge("tenant_alpha", "P001", ("admin",))
        self.assertEqual(property_view["property_id"], "P001")
        self.assertTrue(property_view["documents"])
        self.assertTrue(property_view["active_contracts"])

        unit_view = self.service.unit_knowledge("tenant_alpha", "U305", ("restricted",))
        document_ids = {document["document_id"] for document in unit_view["documents"]}
        self.assertIn("Aマンション_305号室_賃貸借契約書", document_ids)
        self.assertNotIn("保証人情報", document_ids)

    def test_workflows_and_draft_review_contracts(self) -> None:
        contract = self.service.contract_question(
            "tenant_alpha",
            ("property_manager",),
            {"question": "契約上ペットは可能ですか"},
        )
        self.assertEqual(contract["status"], "ok")
        self.assertTrue(contract["review_required"])
        self.assertEqual(contract["gate_decision"]["blocked"], False)

        repair = self.service.repair_investigation(
            "tenant_alpha",
            ("property_manager",),
            {"symptom": "水漏れ"},
        )
        self.assertEqual(repair["status"], "ok")
        self.assertTrue(repair["similar_cases"])

        occupant = self.service.occupant_reply_draft(
            "tenant_alpha",
            ("property_manager",),
            {"inquiry_text": "水漏れです", "reviewer_group": "pm_leads"},
        )
        self.assertEqual(occupant["artifact_type"], "occupant_reply")
        stored = self.service.draft(occupant["artifact_id"])
        self.assertEqual(stored["created_by"], "ai")
        self.assertFalse(stored["auto_approved"])

        review = self.service.review_draft(
            occupant["artifact_id"],
            {"action": "approve", "reviewer_id": "reviewer_1"},
        )
        self.assertEqual(review["status"], "in_review")

        move_out = self.service.move_out_checklist_draft(
            "tenant_alpha",
            ("property_manager",),
            {"unit_id": "U305"},
        )
        self.assertEqual(move_out["artifact_type"], "move_out_checklist")
        restoration = self.service.restoration_explanation_draft(
            "tenant_alpha",
            ("property_manager",),
            {"unit_id": "U305"},
        )
        self.assertEqual(restoration["artifact_type"], "restoration_explanation")

    def test_dashboard_kpi_audit_and_governance(self) -> None:
        self.service.contract_question(
            "tenant_alpha",
            ("property_manager",),
            {"question": "契約上ペットは可能ですか"},
        )
        self.service.occupant_reply_draft("tenant_alpha", ("property_manager",), {})
        self.service.owner_report_draft("tenant_alpha", ("property_manager",), {})

        dashboard = self.service.dashboard("tenant_alpha", ("admin",))
        widget_ids = {widget["widget_id"] for widget in dashboard["widgets"]}
        self.assertIn("high_risk_query_count", widget_ids)
        self.assertIn("owner_report_draft_count", widget_ids)

        kpi = self.service.kpi("tenant_alpha", ("admin",))
        self.assertGreaterEqual(kpi["high_risk_query_count"], 1)
        self.assertGreaterEqual(kpi["occupant_reply_draft_count"], 1)

        audit = self.service.audit()
        event_types = {event["event_type"] for event in audit["events"]}
        self.assertIn("real_estate.contract_question", event_types)
        self.assertIn("real_estate.draft_generated", event_types)

        governance = self.service.governance_status()
        self.assertEqual(governance["poc_readiness"], "ready")
        self.assertFalse(governance["draft_review"]["auto_approval"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
