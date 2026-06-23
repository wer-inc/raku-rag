from __future__ import annotations

import unittest
from datetime import date

from raku_rag.industry import InvestmentSystem, RealEstateSystem
from raku_rag.industry.common import IndustryCitation
from raku_rag.industry.framework import (
    DraftArtifactService,
    FrameworkAuditEvent,
    FrameworkCostEvent,
    IndustryDashboardService,
    IndustryGovernanceStatusService,
    IndustryKPIService,
    IndustryProfile,
    IndustryProfileService,
    IndustryRiskPolicyService,
    IndustryWorkflowHooks,
    IndustryWorkflowService,
    MetadataSchemaService,
    RecordRetentionPolicyService,
    RequiredEvidencePolicyService,
    WorkflowDefinition,
    WorkflowRequest,
    seed_industry_profiles,
)


class IndustryFrameworkProfileTest(unittest.TestCase):
    def setUp(self) -> None:
        self.profiles = seed_industry_profiles()
        self.service = IndustryProfileService(self.profiles)

    def test_seed_profiles_map_002_003_006_to_common_framework(self) -> None:
        ids = {profile.industry_id for profile in self.profiles}
        self.assertEqual(ids, {"manufacturing", "real_estate_pm", "investment_management"})

        manufacturing = self.service.get("manufacturing")
        self.assertIn("equipment_id", manufacturing.metadata_schema.indexed_fields)
        self.assertIn(
            "checklist_draft",
            {workflow.workflow_id for workflow in manufacturing.workflow_definitions},
        )
        self.assertIn(
            "safety_gate_block_count", {kpi.kpi_id for kpi in manufacturing.kpi_definitions}
        )

        real_estate = self.service.get("real_estate_pm")
        self.assertIn("unit_id", real_estate.metadata_schema.indexed_fields)
        self.assertIn(
            "occupant_reply", {draft.artifact_type for draft in real_estate.draft_artifact_types}
        )
        self.assertTrue(real_estate.acl_mapping_policy.pre_filter_required)

        investment = self.service.get("investment_management")
        self.assertIsNotNone(investment.advice_boundary_policy)
        self.assertIsNotNone(investment.disclosure_evidence_policy)
        self.assertIsNotNone(investment.compliance_review_policy)
        self.assertIn("fund_id", investment.acl_mapping_policy.metadata_fields_to_acl)

    def test_profile_resolution_is_tenant_and_collection_scoped(self) -> None:
        self.service.bind_profile("tenant_a", "real_estate_pm")
        self.service.bind_profile("tenant_a", "investment_management", collection_id="funds")

        self.assertEqual(self.service.resolve("tenant_a").industry_id, "real_estate_pm")
        self.assertEqual(
            self.service.resolve("tenant_a", collection_id="funds").industry_id,
            "investment_management",
        )
        with self.assertRaises(KeyError):
            self.service.resolve("tenant_b")


class MetadataSchemaServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = IndustryProfileService(seed_industry_profiles()).get("real_estate_pm")
        self.service = MetadataSchemaService((self.profile.metadata_schema,))

    def test_schema_validation_enforces_required_fields_and_types(self) -> None:
        metadata = {
            "tenant_id": "tenant_alpha",
            "collection_id": "leases",
            "document_id": "lease_305",
            "approval_status": "approved",
            "effective_date": "2026-01-10",
            "access_scope": "unit",
            "acl_tags": "pm",
            "no_train_policy_ref": "default_no_train",
            "retention_policy_ref": "default_retention",
            "property_id": "P001",
            "unit_id": "U305",
        }
        self.assertTrue(self.service.validate("real_estate_pm", metadata).valid)

        invalid = dict(metadata)
        invalid["document_id"] = ""
        invalid["property_id"] = 123
        result = self.service.validate("real_estate_pm", invalid)
        self.assertFalse(result.valid)
        self.assertIn("missing required field: document_id", result.errors)
        self.assertIn("field property_id expected string", result.errors)


class RiskAndEvidencePolicyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = IndustryProfileService(seed_industry_profiles()).get("investment_management")
        self.risk = IndustryRiskPolicyService()
        self.evidence = RequiredEvidencePolicyService(today=date(2026, 6, 20))

    def test_rule_based_risk_and_uncertain_case_high_risk_default(self) -> None:
        decision = self.risk.evaluate(
            self.profile.risk_policy, "この顧客にFUND-001を買わせるべきか"
        )
        self.assertTrue(decision.high_risk)
        self.assertIn("advice_boundary", decision.risk_categories)
        self.assertIn("im_advice", decision.matched_rules)

        uncertain = self.risk.evaluate(
            self.profile.risk_policy, "どうしたらよいですか", uncertain=True
        )
        self.assertTrue(uncertain.high_risk)
        self.assertEqual(uncertain.decision, "review_required")
        self.assertIn("uncertain", uncertain.risk_categories)

    def test_required_evidence_requires_approved_effective_citations(self) -> None:
        policy = self.profile.required_evidence_policy
        approved = IndustryCitation(
            "prospectus",
            "prospectus",
            approval_status="approved",
            effective_date="2026-01-10",
        )
        self.assertTrue(self.evidence.check(policy, (approved,)).passed)

        draft = IndustryCitation(
            "draft_material",
            "marketing_material",
            approval_status="draft",
            effective_date="2026-01-10",
        )
        result = self.evidence.check(policy, (draft,))
        self.assertFalse(result.passed)
        self.assertEqual(result.status, "insufficient_evidence")

        missing_date = IndustryCitation(
            "old_material",
            "marketing_material",
            approval_status="approved",
            effective_date=None,
        )
        result = self.evidence.check(policy, (missing_date,))
        self.assertFalse(result.passed)
        self.assertIn("effective date missing or invalid", result.reasons)


class DraftArtifactServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = IndustryProfileService(seed_industry_profiles()).get("real_estate_pm")
        self.service = DraftArtifactService()
        self.citation = IndustryCitation("repair_history", "repair_history")

    def test_ai_created_draft_cannot_auto_approve(self) -> None:
        draft = self.service.create(
            self.profile,
            "occupant_reply",
            source_citations=(self.citation,),
            source_document_ids=("repair_history",),
            payload={"body": "draft reply"},
        )
        self.assertEqual(draft.status, "draft")
        self.assertEqual(draft.created_by, "ai")
        with self.assertRaises(PermissionError):
            self.service.transition(self.profile, draft.artifact_id, to_status="approved")

        in_review = self.service.transition(
            self.profile,
            draft.artifact_id,
            to_status="in_review",
            reviewer_id="reviewer_1",
            reviewer_role="reviewer",
        )
        self.assertEqual(in_review.status, "in_review")
        approved = self.service.transition(
            self.profile,
            draft.artifact_id,
            to_status="approved",
            reviewer_id="reviewer_1",
            reviewer_role="reviewer",
        )
        self.assertEqual(approved.status, "approved")

    def test_draft_generation_review_assignment_and_archive_emit_audit(self) -> None:
        draft = self.service.create(
            self.profile,
            "occupant_reply",
            source_citations=(self.citation,),
            tenant_id="tenant_alpha",
            actor_id="operator_1",
        )
        self.service.transition(
            self.profile,
            draft.artifact_id,
            to_status="in_review",
            reviewer_id="reviewer_1",
            reviewer_role="reviewer",
            tenant_id="tenant_alpha",
        )
        approved = self.service.transition(
            self.profile,
            draft.artifact_id,
            to_status="approved",
            reviewer_id="reviewer_1",
            reviewer_role="reviewer",
            tenant_id="tenant_alpha",
        )
        self.service.transition(
            self.profile,
            approved.artifact_id,
            to_status="archived",
            reviewer_id="reviewer_1",
            reviewer_role="reviewer",
            tenant_id="tenant_alpha",
        )

        actions = [event.action for event in self.service.audit_events()]
        self.assertIn("draft.generated", actions)
        self.assertIn("draft.assigned", actions)
        self.assertIn("draft.review_transition", actions)
        self.assertIn("draft.archived", actions)


class IndustryWorkflowServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.profile_service = IndustryProfileService(seed_industry_profiles())
        self.evidence = RequiredEvidencePolicyService(today=date(2026, 6, 20))

    def test_definitive_workflow_calls_retrieval_answer_citation_audit_and_cost(self) -> None:
        calls: list[tuple[str, object]] = []
        audit_events: list[FrameworkAuditEvent] = []
        cost_events: list[FrameworkCostEvent] = []

        def retrieve(
            _request: WorkflowRequest,
            profile: IndustryProfile,
            workflow: WorkflowDefinition,
        ) -> tuple[IndustryCitation, ...]:
            calls.append(("retrieve", (profile.industry_id, workflow.workflow_id)))
            return (
                IndustryCitation(
                    "lease_305",
                    "lease_contract",
                    approval_status="approved",
                    effective_date="2026-01-10",
                ),
            )

        def answer(
            _request: WorkflowRequest,
            _profile: IndustryProfile,
            _workflow: WorkflowDefinition,
            citations: tuple[IndustryCitation, ...],
        ) -> str:
            calls.append(("answer", tuple(citation.document_id for citation in citations)))
            return "approved lease evidence says pets are allowed with prior approval"

        def citation_access(
            _request: WorkflowRequest,
            _profile: IndustryProfile,
            _workflow: WorkflowDefinition,
            citations: tuple[IndustryCitation, ...],
        ) -> None:
            calls.append(("citation", tuple(citation.document_id for citation in citations)))

        service = IndustryWorkflowService(
            self.profile_service,
            evidence_service=self.evidence,
            hooks=IndustryWorkflowHooks(
                retrieve=retrieve,
                answer=answer,
                citation_access=citation_access,
                audit=audit_events.append,
                cost=cost_events.append,
            ),
        )

        result = service.run(
            WorkflowRequest(
                tenant_id="tenant_alpha",
                industry_id="real_estate_pm",
                workflow_id="contract_question",
                query="契約上ペットは可能ですか",
                actor_id="operator_1",
                metadata={"property_id": "P001", "unit_id": "U305"},
            )
        )

        self.assertEqual(result.status, "ok")
        self.assertEqual(
            result.text,
            "approved lease evidence says pets are allowed with prior approval",
        )
        self.assertEqual(result.profile.industry_id, "real_estate_pm")
        self.assertIn("contract_condition", result.risk_decision.risk_categories)
        self.assertEqual([citation.document_id for citation in result.citations], ["lease_305"])
        self.assertEqual(
            calls,
            [
                ("retrieve", ("real_estate_pm", "contract_question")),
                ("citation", ("lease_305",)),
                ("answer", ("lease_305",)),
            ],
        )
        self.assertEqual(
            [event.action for event in result.audit_events],
            [
                "workflow.started",
                "risk.decision",
                "evidence.decision",
                "citation.access",
                "workflow.completed",
            ],
        )
        self.assertEqual(result.audit_events, tuple(audit_events))
        self.assertEqual([event.kind for event in result.cost_events], ["retrieval", "answer"])
        self.assertEqual(result.cost_events, tuple(cost_events))

    def test_insufficient_evidence_blocks_before_answer_and_citation_access(self) -> None:
        calls: list[str] = []
        audit_events: list[FrameworkAuditEvent] = []

        def retrieve(
            _request: WorkflowRequest,
            _profile: IndustryProfile,
            _workflow: WorkflowDefinition,
        ) -> tuple[IndustryCitation, ...]:
            calls.append("retrieve")
            return (
                IndustryCitation(
                    "draft_rule",
                    "management_rule",
                    approval_status="draft",
                    effective_date="2026-01-10",
                ),
            )

        def answer(
            _request: WorkflowRequest,
            _profile: IndustryProfile,
            _workflow: WorkflowDefinition,
            _citations: tuple[IndustryCitation, ...],
        ) -> str:
            calls.append("answer")
            return "should not be called"

        def citation_access(
            _request: WorkflowRequest,
            _profile: IndustryProfile,
            _workflow: WorkflowDefinition,
            _citations: tuple[IndustryCitation, ...],
        ) -> None:
            calls.append("citation")

        service = IndustryWorkflowService(
            self.profile_service,
            evidence_service=self.evidence,
            hooks=IndustryWorkflowHooks(
                retrieve=retrieve,
                answer=answer,
                citation_access=citation_access,
                audit=audit_events.append,
            ),
        )

        result = service.run(
            WorkflowRequest(
                tenant_id="tenant_alpha",
                industry_id="real_estate_pm",
                workflow_id="contract_question",
                query="契約上ペットは可能ですか",
                metadata={"property_id": "P001", "unit_id": "U305"},
            )
        )

        self.assertEqual(result.status, "insufficient_evidence")
        self.assertTrue(result.blocked)
        self.assertTrue(result.review_required)
        self.assertEqual(calls, ["retrieve"])
        self.assertEqual(result.citations, ())
        self.assertIn(
            "approval status draft is not approved",
            result.evidence_decision.reasons,
        )
        self.assertEqual([event.action for event in audit_events][-1], "workflow.completed")

    def test_draft_workflow_creates_artifact_and_records_cost(self) -> None:
        service = IndustryWorkflowService(
            self.profile_service,
            evidence_service=self.evidence,
            hooks=IndustryWorkflowHooks(
                retrieve=lambda _request, _profile, _workflow: (
                    IndustryCitation(
                        "repair_history_7",
                        "repair_history",
                        approval_status="approved",
                        effective_date="2026-01-10",
                    ),
                )
            ),
        )

        result = service.run(
            WorkflowRequest(
                tenant_id="tenant_alpha",
                industry_id="real_estate_pm",
                workflow_id="occupant_reply_draft",
                query="修繕履歴を踏まえて入居者返信案を作成してください",
                metadata={"property_id": "P001", "unit_id": "U305"},
                payload={"body": "修繕履歴に基づく返信案"},
            )
        )

        self.assertEqual(result.status, "draft")
        self.assertIsNotNone(result.draft_artifact)
        assert result.draft_artifact is not None
        self.assertEqual(result.draft_artifact.artifact_type, "occupant_reply")
        self.assertEqual(result.draft_artifact.status, "draft")
        self.assertEqual(result.draft_artifact.source_document_ids, ("repair_history_7",))
        self.assertEqual(result.draft_artifact.payload["body"], "修繕履歴に基づく返信案")
        self.assertEqual([event.kind for event in result.cost_events], ["retrieval", "draft"])
        self.assertEqual(result.audit_events[-1].decision, "draft")


class IndustryKpiDashboardGovernanceRetentionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = IndustryProfileService(seed_industry_profiles()).get("real_estate_pm")

    def test_kpi_dashboard_filters_by_tenant_role_and_industry(self) -> None:
        audit_events = (
            FrameworkAuditEvent("tenant_alpha", "real_estate_pm", "contract_question", "x", "ok"),
            FrameworkAuditEvent("tenant_beta", "real_estate_pm", "contract_question", "x", "ok"),
            FrameworkAuditEvent("tenant_alpha", "manufacturing", "checklist_draft", "x", "ok"),
        )
        values = IndustryKPIService().calculate(
            self.profile, tenant_id="tenant_alpha", audit_events=audit_events
        )
        self.assertTrue(all(value.tenant_id == "tenant_alpha" for value in values))
        self.assertEqual(values[1].source_event_count, 1)

        dashboard = IndustryDashboardService().render(
            self.profile,
            tenant_id="tenant_alpha",
            roles=("standard_user",),
            kpi_values=values,
        )
        self.assertEqual(dashboard.widgets, ())
        self.assertEqual(dashboard.denied_widget_ids, ("real_estate_pm_overview",))

        admin_dashboard = IndustryDashboardService().render(
            self.profile,
            tenant_id="tenant_alpha",
            roles=("admin",),
            kpi_values=values,
            allowed_industry_ids=("real_estate_pm",),
        )
        self.assertEqual(admin_dashboard.widgets[0]["widget_id"], "real_estate_pm_overview")
        self.assertTrue(all(kpi.industry_id == "real_estate_pm" for kpi in admin_dashboard.kpis))

    def test_governance_status_delegates_001_facts(self) -> None:
        ready = IndustryGovernanceStatusService().status(
            self.profile,
            provider_facts={"no_train_required": True, "zero_retention_required": True},
            audit_facts={"audit_sink_ready": True},
            no_train_facts={"enforced": True},
            retention_facts={"retention_controls_ready": True},
        )
        self.assertEqual(ready.status, "ready")
        self.assertTrue(ready.no_train_enforced)
        self.assertTrue(ready.retention_ready)

        action_required = IndustryGovernanceStatusService().status(
            self.profile,
            provider_facts={"no_train_required": False, "zero_retention_required": True},
        )
        self.assertEqual(action_required.status, "action_required")

    def test_retention_policy_decision_uses_profile_contract(self) -> None:
        assert self.profile.record_retention_policy is not None
        decision = RecordRetentionPolicyService(today=date(2026, 6, 20)).decide(
            self.profile.record_retention_policy,
            document_id="lease_305",
            effective_date="2026-01-10",
        )
        self.assertEqual(decision.retention_policy_ref, "real_estate_pm_retention")
        self.assertEqual(decision.retain_until, "2033-01-08")
        self.assertTrue(decision.export_allowed)
        self.assertTrue(decision.delete_allowed)

        held = RecordRetentionPolicyService(today=date(2026, 6, 20)).decide(
            self.profile.record_retention_policy,
            document_id="lease_305",
            legal_hold=True,
        )
        self.assertFalse(held.delete_allowed)


class IndustryRuntimeFrameworkIntegrationTest(unittest.TestCase):
    def test_real_estate_runtime_uses_common_profile_and_risk_trace(self) -> None:
        system = RealEstateSystem()
        answer = system.contract_condition(RealEstateSystem.operator(), "契約上ペットは可能ですか")
        self.assertEqual(system.profile.industry_id, "real_estate_pm")
        self.assertEqual(answer.status, "ok")
        risk_event = next(
            event for event in answer.audit_events if event.action == "real_estate.risk_decision"
        )
        self.assertIn("framework_decision", risk_event.metadata)
        self.assertIn("re_contract", risk_event.metadata["matched_rules"])

    def test_investment_runtime_uses_common_profile_and_regulated_extensions(self) -> None:
        system = InvestmentSystem()
        answer = system.advice_boundary(InvestmentSystem.operator(), "この顧客に買わせるべきか")
        self.assertEqual(system.profile.industry_id, "investment_management")
        self.assertIsNotNone(system.profile.advice_boundary_policy)
        self.assertEqual(answer.status, "blocked")
        risk_event = next(
            event for event in answer.audit_events if event.action == "investment.advice_boundary"
        )
        self.assertIn("framework_decision", risk_event.metadata)
        self.assertIn("im_advice", risk_event.metadata["matched_rules"])


class InvestmentRegulatedPolicyTest(unittest.TestCase):
    """GAP-F13: the declared MarketingMaterialPolicy governs the contradiction check at runtime."""

    def test_marketing_policy_governs_disclosure_outcome(self) -> None:
        from dataclasses import replace

        system = InvestmentSystem()
        user = InvestmentSystem.operator()
        statements = ("過去実績は良好でした",)
        # With risk-disclosure required (default), a performance claim with no disclosure is flagged.
        _draft, with_req = system.marketing_material_check(user, statements)
        self.assertEqual(with_req[0]["contradiction_type"], "risk_disclosure_missing")
        # Flipping the policy field changes the runtime outcome (proves the policy governs).
        relaxed = InvestmentSystem()
        relaxed.profile = replace(
            relaxed.profile,
            marketing_material_policy=replace(
                relaxed.profile.marketing_material_policy, risk_disclosure_required=False
            ),
        )
        _draft2, without_req = relaxed.marketing_material_check(user, statements)
        self.assertEqual(without_req, ())

    def test_disclosure_policy_governs_marketing_source_selection(self) -> None:
        from dataclasses import replace

        system = InvestmentSystem()
        policy = system.profile.disclosure_evidence_policy
        system.profile = replace(
            system.profile,
            disclosure_evidence_policy=replace(
                policy, required_source_document_types=("monthly_report",)
            ),
        )

        draft, _results = system.marketing_material_check(
            InvestmentSystem.operator(), ("過去実績はリスク開示付きで確認します",)
        )

        self.assertEqual(draft.source_document_ids, ("FUND-001_月報_2025-05",))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
