from __future__ import annotations

import unittest

from raku_rag.industry import IndustryApiService


class IndustryApiServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.service = IndustryApiService()

    def test_list_and_profile_expose_generic_industry_contract(self) -> None:
        listing = self.service.list_industries(tenant_id="tenant_alpha")
        ids = {item["industry_id"] for item in listing["industries"]}
        self.assertEqual(ids, {"manufacturing", "real_estate_pm", "investment_management"})

    def test_manufacturing_workflow_run_is_refused_redirecting_to_bespoke_surface(self) -> None:
        # The generic (caller-citation, no-safety-gate) workflow path must NOT answer for
        # manufacturing — that vertical has the bespoke safety-gated /v1/manufacturing/* surface.
        # The PROFILE is still exposed (above); only the answering workflow run is refused.
        self.service.profile("manufacturing")  # profile still available
        with self.assertRaises(ValueError):
            self.service.run_workflow(
                "tenant_alpha", "operator_1", "manufacturing", "any_workflow", {"query": "x"}
            )

        profile = self.service.profile("real_estate_pm")
        self.assertEqual(profile["industry_id"], "real_estate_pm")
        self.assertIn("metadata_schema", profile)
        self.assertIn(
            "contract_question", {workflow["workflow_id"] for workflow in profile["workflows"]}
        )
        self.assertIn(
            "occupant_reply", {draft["artifact_type"] for draft in profile["draft_artifact_types"]}
        )

    def test_metadata_validate_and_document_enrich_apply_common_controls(self) -> None:
        invalid = self.service.validate_metadata(
            "real_estate_pm",
            {"metadata": {"tenant_id": "tenant_alpha"}},
        )
        self.assertFalse(invalid["valid"])
        self.assertIn("missing required field: document_id", invalid["errors"])

        enriched = self.service.enrich_document(
            "tenant_alpha",
            "real_estate_pm",
            {
                "document_id": "lease_305",
                "collection_id": "leases",
                "document_type": "lease_contract",
                "metadata": {"property_id": "P001", "unit_id": "U305"},
                "effective_date": "2026-01-10",
            },
        )
        self.assertTrue(enriched["validation"]["valid"])
        self.assertEqual(enriched["metadata"]["tenant_id"], "tenant_alpha")
        self.assertEqual(enriched["metadata"]["no_train_policy_ref"], "default_no_train")
        self.assertEqual(
            enriched["retention_decision"]["retention_policy_ref"], "real_estate_pm_retention"
        )

    def test_workflow_draft_dashboard_kpi_and_governance_endpoints(self) -> None:
        workflow = self.service.run_workflow(
            "tenant_alpha",
            "operator_1",
            "real_estate_pm",
            "contract_question",
            {
                "query": "契約上ペットは可能ですか",
                "metadata": {"property_id": "P001", "unit_id": "U305"},
                "citations": [
                    {
                        "document_id": "lease_305",
                        "document_type": "lease_contract",
                        "approval_status": "approved",
                        "effective_date": "2026-01-10",
                    }
                ],
            },
        )
        self.assertEqual(workflow["status"], "ok")
        self.assertEqual(workflow["citations"][0]["document_id"], "lease_305")

        draft = self.service.create_draft(
            "tenant_alpha",
            "operator_1",
            "real_estate_pm",
            "occupant_reply",
            {
                "payload": {"body": "draft"},
                "citations": [
                    {
                        "document_id": "repair_history_7",
                        "document_type": "repair_history",
                        "approval_status": "approved",
                        "effective_date": "2026-01-10",
                    }
                ],
            },
        )
        artifact_id = draft["draft"]["artifact_id"]
        self.assertEqual(self.service.get_draft("real_estate_pm", artifact_id)["status"], "draft")

        reviewed = self.service.review_draft(
            "tenant_alpha",
            "reviewer_1",
            "real_estate_pm",
            artifact_id,
            {"to_status": "in_review", "reviewer_role": "reviewer"},
        )
        self.assertEqual(reviewed["draft"]["status"], "in_review")

        kpi = self.service.kpi("tenant_alpha", "real_estate_pm")
        self.assertTrue(kpi["kpis"])
        dashboard = self.service.dashboard("tenant_alpha", "real_estate_pm", roles=("admin",))
        self.assertEqual(dashboard["widgets"][0]["widget_id"], "real_estate_pm_overview")
        governance = self.service.governance_status("real_estate_pm")
        self.assertEqual(governance["status"], "ready")

    def test_profile_version_report_keeps_existing_industry_mappings_stable(self) -> None:
        report = self.service.profile_version_report()
        self.assertTrue(report["stable"])
        by_id = {profile["industry_id"]: profile for profile in report["profiles"]}
        self.assertEqual(by_id["manufacturing"]["metadata_schema_version"], 1)
        self.assertGreaterEqual(by_id["real_estate_pm"]["workflow_count"], 4)
        self.assertGreaterEqual(by_id["investment_management"]["document_type_count"], 4)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
