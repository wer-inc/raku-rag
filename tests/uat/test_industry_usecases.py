"""Executable UAT coverage for the industry use cases.

The source list lives in ``docs/uat/industry-usecases.md``. These tests keep one public test per
case ID so the verification report can honestly say which scenarios are executable.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook

from raku_rag.domain.models import Citation, IdentityClaims, ScopeType, SubjectType
from raku_rag.industry import InvestmentSystem, RealEstateSystem
from raku_rag.manufacturing.app import ManufacturingSystem
from raku_rag.manufacturing.domain.acl_mapping import ManufacturingScope, factory_scope
from raku_rag.manufacturing.domain.draft import CreatedBy, DraftStatus, DraftType
from raku_rag.manufacturing.domain.entities import (
    Countermeasure,
    CountermeasureType,
    FailureMode,
    MeasureClass,
    TroubleCase,
)
from raku_rag.manufacturing.domain.metadata import (
    ApprovalStatus,
    DocumentKind,
    ManufacturingDocumentMetadata,
)
from raku_rag.manufacturing.domain.policy import NoTrainFallback
from raku_rag.manufacturing.domain.safety import SafetyBlockReason
from tests.helpers import claims as base_claims
from tests.helpers import fresh as fresh_base
from tests.manufacturing.helpers import T as MFG_T
from tests.manufacturing.helpers import claims as mfg_claims
from tests.manufacturing.helpers import mfg_meta

XLSX_CT = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _enum_value(value):
    return getattr(value, "value", value)


def _attr_or_key(obj, name):
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _citation_ids(citations) -> set[str]:
    return {citation.document_id for citation in citations}


def _audit_actions(events) -> set[str]:
    return {event.action for event in events}


class CrossIndustryUseCases(unittest.TestCase):
    def test_x_01_tenant_and_acl_boundary_prevents_cross_tenant_leakage(self) -> None:
        sys = fresh_base()
        shared = "The hydraulic press reset sequence for E-142 is documented in section four."
        sys.ingest_text(
            tenant_id="tenant_alpha", collection_id="manuals", document_id="alpha", text=shared
        )
        sys.ingest_text(
            tenant_id="tenant_beta", collection_id="manuals", document_id="beta", text=shared
        )
        sys.grant("tenant_alpha", ScopeType.COLLECTION, "manuals", SubjectType.USER, "alice")
        sys.grant("tenant_beta", ScopeType.COLLECTION, "manuals", SubjectType.USER, "bob")
        alice = base_claims("tenant_alpha", "alice")

        results = sys.search(alice, "hydraulic press reset E-142")
        self.assertTrue(results)
        self.assertEqual(sys.store.last_prefiltered_count, 1)
        self.assertEqual({r.chunk.tenant_id for r in results}, {"tenant_alpha"})
        self.assertNotIn("beta", {r.chunk.document_id for r in results})

        answer = sys.answer(alice, "what is the E-142 reset sequence?")
        self.assertEqual(answer.status, "ok")
        self.assertEqual(_citation_ids(answer.citations), {"alpha"})

    def test_x_02_deleted_documents_never_reappear_in_answer_search_or_cache(self) -> None:
        sys = fresh_base()
        sys.ingest_text(
            tenant_id="tenant_alpha",
            collection_id="manuals",
            document_id="retired_doc",
            text="The retired emergency contact is 555-0100 for the escalation runbook.",
        )
        sys.grant("tenant_alpha", ScopeType.COLLECTION, "manuals", SubjectType.USER, "alice")
        alice = base_claims("tenant_alpha", "alice")

        before = sys.answer(alice, "what is the retired emergency contact?")
        self.assertEqual(before.status, "ok")
        self.assertEqual(_citation_ids(before.citations), {"retired_doc"})
        sys.cache.put("tenant_alpha", "q:retired-contact", before, {"retired_doc"})

        deletion = sys.deletion.delete("tenant_alpha", "retired_doc")
        self.assertGreaterEqual(deletion.invalidated_cache_entries, 1)
        self.assertIsNone(sys.cache.get("tenant_alpha", "q:retired-contact"))

        after = sys.answer(alice, "what is the retired emergency contact?")
        self.assertEqual(after.status, "insufficient_evidence")
        self.assertEqual(after.used_chunks, ())
        self.assertEqual(sys.search(alice, "retired emergency contact"), [])

    def test_x_03_no_train_default_blocks_unverified_providers_and_training_use(self) -> None:
        sys = ManufacturingSystem(
            provider_capabilities={"external_parser": ("leaky_provider",)},
            no_train_providers=(),
        )
        policy = sys.get_data_use_policy(MFG_T)
        self.assertTrue(policy.no_train_default)
        self.assertFalse(policy.training_opt_in)
        self.assertEqual(policy.no_train_fallback, NoTrainFallback.BLOCK)
        self.assertEqual(sys.capability_status(MFG_T, "external_parser"), "temporarily_unavailable")
        with self.assertRaises(Exception):
            sys.use_for_training(
                tenant_id=MFG_T,
                data_kind="answer",
                actor=IdentityClaims(tenant_id=MFG_T, user_id="admin", roles=("admin",)),
            )

    def test_x_04_raw_context_is_not_stored_while_reference_metadata_is_retained(self) -> None:
        root = Path(__file__).resolve().parents[2]
        enforcer = (root / "apps/api/src/observability/logging-policy.service.ts").read_text(
            encoding="utf-8"
        )
        e2e = (root / "apps/api/test/observability.e2e-spec.ts").read_text(encoding="utf-8")

        for token in (
            'raw_retrieved_context_storage: "disabled"',
            "shouldStoreRaw",
            "citation_ids",
            "chunk_ids",
            "document_ids",
            "store_citation_ids",
            "store_chunk_ids",
        ):
            with self.subTest(token=token):
                self.assertIn(token, enforcer)
        self.assertIn('not.toContain("RAW_CONTEXT_SECRET")', e2e)


class ManufacturingUseCases(unittest.TestCase):
    def setUp(self) -> None:
        self.sys = ManufacturingSystem()
        self.operator = mfg_claims(MFG_T, "op")

    def test_mfg_01_equipment_error_answer_uses_approved_evidence_and_cell_anchor(self) -> None:
        self.sys.grant(MFG_T, ScopeType.COLLECTION, "maintenance", SubjectType.USER, "op")
        with tempfile.TemporaryDirectory() as tmpdir:
            xlsx = Path(tmpdir) / "press-ledger.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            sheet.title = "E142"
            sheet.append(["equipment", "alarm", "remedy"])
            sheet.append(
                ["EQ-PRESS-100", "E-142", "Check air pressure, reset, then record result."]
            )
            workbook.save(str(xlsx))

            job = self.sys.ingest_manufacturing_file(
                tenant_id=MFG_T,
                collection_id="maintenance",
                document_id="EQ-PRESS-100_E142_ledger",
                path=str(xlsx),
                content_type=XLSX_CT,
                metadata=ManufacturingDocumentMetadata(
                    tenant_id=MFG_T,
                    document_id="EQ-PRESS-100_E142_ledger",
                    equipment="EQ-PRESS-100",
                    alarm_code="E-142",
                    document_kind=DocumentKind.LEDGER,
                    approval_status=ApprovalStatus.APPROVED,
                    effective_date="2026-01-10",
                ),
            )
        self.assertEqual(job.status, "succeeded")

        results = self.sys.search(
            self.operator,
            "EQ-PRESS-100 E-142 air pressure reset",
            collection_id="maintenance",
            manufacturing_filters={"alarm_code": "E-142"},
        )
        hit = next((r for r in results if r.document_id == "EQ-PRESS-100_E142_ledger"), None)
        self.assertIsNotNone(hit)
        self.assertEqual(hit.approval_status, "approved")
        self.assertEqual(hit.effective_date, "2026-01-10")
        self.assertIsNotNone(hit.cell_anchor)
        self.assertIsNotNone(hit.sheet)

    def test_mfg_02_hazardous_work_blocks_without_approved_effective_safety_evidence(self) -> None:
        self.sys.ingest_manufacturing(
            tenant_id=MFG_T,
            collection_id="safety",
            document_id="draft_press_disassembly",
            text="Draft note: disassemble the press after removing the guard.",
            metadata=mfg_meta(
                tenant_id=MFG_T,
                document_id="draft_press_disassembly",
                approval_status=ApprovalStatus.DRAFT,
                effective_date=None,
                document_kind=DocumentKind.WORK_INSTRUCTION,
                safety_category="lockout_tagout",
                hazard_tags=("設備停止", "分解", "高圧"),
            ),
        )
        self.sys.grant(MFG_T, ScopeType.COLLECTION, "safety", SubjectType.USER, "op")

        answer = self.sys.answer(self.operator, "How do I disassemble the press safely?")
        self.assertTrue(answer.high_risk)
        self.assertEqual(answer.status, "insufficient_evidence")
        self.assertEqual(
            answer.safety_block_reason,
            SafetyBlockReason.APPROVED_CITATION_MISSING.value,
        )
        self.assertFalse(answer.text)
        self.assertEqual(answer.citations, ())

    def test_mfg_03_similar_trouble_case_returns_causes_and_candidate_measures(self) -> None:
        self._seed_press_trouble_case()
        self.sys.grant(MFG_T, ScopeType.COLLECTION, "quality", SubjectType.USER, "op")

        response = self.sys.search_trouble_cases(
            self.operator,
            "PN-10024 cracked bracket abnormal vibration E-142",
            collection_id="quality",
        )
        self.assertEqual(_enum_value(response.status), "ok")
        match = next(
            (item for item in response.results if item.trouble_case_id == "PN-10024"), None
        )
        self.assertIsNotNone(match)
        self.assertEqual(match.failure_mode.name, "締結トルク不足")
        self.assertTrue(match.recurrence_prevention)
        self.assertTrue(match.citations)
        self.assertIn("PN-10024_quality_report", _citation_ids(match.citations))
        self.assertIn(
            "cm_provisional", {item.measure_id for item in match.countermeasures.provisional}
        )
        permanent = next(
            item for item in match.countermeasures.permanent if item.measure_id == "cm_perm"
        )
        self.assertEqual(_enum_value(permanent.measure_class), MeasureClass.PERMANENT.value)
        self.assertEqual(_enum_value(permanent.type), CountermeasureType.CANDIDATE.value)

    def test_mfg_04_generated_checklist_is_draft_with_sources_and_never_self_approved(self) -> None:
        artifact = self.sys.generate_draft(
            principal=self.operator,
            kind=DraftType.CHECKLIST,
            context_citations=(
                Citation(
                    kind="text",
                    document_id="EQ-PRESS-100_E142_ledger",
                    source_id="src",
                    version=1,
                    retrieval_score=0.97,
                    chunk_id="EQ-PRESS-100_E142_ledger#0",
                ),
            ),
            source_document_ids=("EQ-PRESS-100_E142_ledger",),
        )
        self.assertEqual(_enum_value(artifact.status), DraftStatus.DRAFT.value)
        self.assertEqual(_enum_value(artifact.created_by), CreatedBy.AI.value)
        self.assertIn("EQ-PRESS-100_E142_ledger", artifact.source_document_ids)
        self.assertTrue(artifact.source_citations)

        with self.assertRaises((PermissionError, ValueError, TypeError)):
            self.sys.review_draft(
                tenant_id=MFG_T,
                artifact_id=artifact.artifact_id,
                reviewer=None,
                decision="approved",
            )
        self.assertEqual(
            _enum_value(self.sys.get_draft(MFG_T, artifact.artifact_id).status),
            DraftStatus.DRAFT.value,
        )

    def test_mfg_05_obsolete_or_draft_material_is_not_formal_primary_evidence(self) -> None:
        self.sys.ingest_manufacturing(
            tenant_id=MFG_T,
            collection_id="maintenance",
            document_id="old_torque_spec",
            text="The torque specification for the bracket bolt is forty newton meters.",
            metadata=mfg_meta(
                tenant_id=MFG_T,
                document_id="old_torque_spec",
                approval_status=ApprovalStatus.OBSOLETE,
                effective_date="2024-01-01",
                obsolete_at="2025-12-31",
                superseded_by="new_torque_spec",
            ),
        )
        self.sys.grant(MFG_T, ScopeType.COLLECTION, "maintenance", SubjectType.USER, "op")

        answer = self.sys.answer(
            self.operator, "what is the torque specification for the bracket bolt?"
        )
        self.assertNotEqual(answer.status, "ok")
        self.assertTrue(answer.obsolete_warning)
        self.assertNotIn("forty newton meters", answer.text or "")

    def test_mfg_06_factory_department_acl_excludes_unauthorized_confidential_documents(
        self,
    ) -> None:
        _, fac_a = factory_scope("F001")
        _, fac_b = factory_scope("F002")
        self.sys.ingest_manufacturing(
            tenant_id=MFG_T,
            collection_id=fac_a,
            document_id="F001_public_doc",
            text="F001 press routine lubrication interval is every two weeks.",
            metadata=mfg_meta(tenant_id=MFG_T, document_id="F001_public_doc"),
        )
        self.sys.ingest_manufacturing(
            tenant_id=MFG_T,
            collection_id=fac_b,
            document_id="F002_confidential_doc",
            text="Customer secret failure mode for EQ-PRESS-200 is cathode delamination.",
            metadata=mfg_meta(
                tenant_id=MFG_T,
                document_id="F002_confidential_doc",
                customer="SecretCustomer",
                defect_type="cathode-delamination",
            ),
        )
        self.sys.grant_scope(
            ManufacturingScope(
                tenant_id=MFG_T,
                department="maintenance",
                roles=("technician",),
                factory_ids=("F001",),
            )
        )
        user = mfg_claims(MFG_T, "tech", groups=("maintenance",), roles=("technician",))

        results = self.sys.search(user, "SecretCustomer cathode delamination EQ-PRESS-200")
        self.assertNotIn("F002_confidential_doc", {item.document_id for item in results})
        self.assertEqual(self.sys._mvp.store.last_prefiltered_count, 1)
        answer = self.sys.answer(user, "what happened to SecretCustomer EQ-PRESS-200?")
        self.assertNotIn("F002_confidential_doc", _citation_ids(answer.citations))
        self.assertNotIn("SecretCustomer", answer.text or "")

    def test_mfg_07_dashboard_kpi_and_safety_telemetry_are_audit_derived(self) -> None:
        self._drive_dashboard_activity()
        admin = mfg_claims(MFG_T, "admin", roles=("admin",))

        telemetry = self.sys.safety_telemetry(admin, factory_id="F001", department_id="dept_press")
        self.assertGreaterEqual(_attr_or_key(telemetry, "high_risk_query_count"), 1)
        block_count = _attr_or_key(telemetry, "safety_gate_block_count")
        breakdown = _attr_or_key(telemetry, "block_breakdown") or _attr_or_key(
            telemetry, "safety_gate_block_breakdown"
        )
        self.assertEqual(_attr_or_key(telemetry, "source"), "audit_log")
        self.assertEqual(sum((breakdown or {}).values()), block_count)

        dashboard = self.sys.knowledge_ops_dashboard(admin)
        self.assertIsNotNone(_attr_or_key(dashboard, "unanswered_question_count"))
        self.assertTrue(_attr_or_key(dashboard, "obsolete_document_candidates"))
        kpi = self.sys.kpi(admin, format="json")
        for key in (
            "self_resolution_rate",
            "grounded_answer_rate",
            "insufficient_evidence_rate",
            "high_risk_query_count",
            "safety_gate_block_count",
        ):
            self.assertIn(key, kpi)
        self.assertIn("self_resolution_rate", self.sys.kpi(admin, format="csv"))

    def _seed_press_trouble_case(self) -> None:
        self.sys.register_trouble_case(
            tenant_id=MFG_T,
            collection_id="quality",
            source_document_id="PN-10024_quality_report",
            text=(
                "Quality report PN-10024: cracked bracket after abnormal vibration on EQ-PRESS-100. "
                "Root cause: insufficient fastening torque. Provisional countermeasure: stop shipment "
                "and inspect inventory. Permanent countermeasure: revise torque checklist and add audit. "
                "Recurrence prevention: add torque witness mark inspection."
            ),
            metadata=ManufacturingDocumentMetadata(
                tenant_id=MFG_T,
                document_id="PN-10024_quality_report",
                document_kind=DocumentKind.QUALITY_REPORT,
                quality_category="bracket_crack",
                part_no="PN-10024",
                approval_status=ApprovalStatus.APPROVED,
                effective_date="2026-01-10",
            ),
            trouble_case=TroubleCase(
                tenant_id=MFG_T,
                trouble_case_id="PN-10024",
                symptom="cracked bracket and abnormal vibration",
                equipment_id="EQ-PRESS-100",
                process_id="press",
                failure_mode_id="fm_torque",
                source_document_id="PN-10024_quality_report",
            ),
            failure_mode=FailureMode(
                tenant_id=MFG_T,
                failure_mode_id="fm_torque",
                name="締結トルク不足",
                description="insufficient fastening torque",
            ),
            countermeasures=(
                Countermeasure(
                    tenant_id=MFG_T,
                    measure_id="cm_provisional",
                    trouble_case_id="PN-10024",
                    description="stop shipment and inspect inventory",
                    measure_class=MeasureClass.PROVISIONAL,
                    source_document_id="PN-10024_quality_report",
                ),
                Countermeasure(
                    tenant_id=MFG_T,
                    measure_id="cm_perm",
                    trouble_case_id="PN-10024",
                    description="revise torque checklist and add audit",
                    measure_class=MeasureClass.PERMANENT,
                    source_document_id="PN-10024_quality_report",
                ),
            ),
            recurrence_prevention="add torque witness mark inspection",
        )

    def _drive_dashboard_activity(self) -> None:
        self.sys.ingest_manufacturing(
            tenant_id=MFG_T,
            collection_id="c",
            document_id="approved_lockout",
            text="Approved lockout tagout: isolate, lock, tag, verify zero energy before disassembly.",
            metadata=mfg_meta(
                tenant_id=MFG_T,
                document_id="approved_lockout",
                approval_status=ApprovalStatus.APPROVED,
                effective_date="2026-01-10",
                document_kind=DocumentKind.WORK_INSTRUCTION,
                safety_category="lockout_tagout",
                hazard_tags=("設備停止", "分解"),
            ),
        )
        self.sys.ingest_manufacturing(
            tenant_id=MFG_T,
            collection_id="c",
            document_id="draft_voltage",
            text="Draft note about working on the 400V panel without full approval.",
            metadata=mfg_meta(
                tenant_id=MFG_T,
                document_id="draft_voltage",
                approval_status=ApprovalStatus.DRAFT,
                effective_date=None,
                document_kind=DocumentKind.WORK_INSTRUCTION,
                safety_category="electrical",
                hazard_tags=("感電", "高圧"),
            ),
        )
        self.sys.ingest_manufacturing(
            tenant_id=MFG_T,
            collection_id="c",
            document_id="obsolete_spec",
            text="Old bracket torque spec note.",
            metadata=mfg_meta(
                tenant_id=MFG_T,
                document_id="obsolete_spec",
                approval_status=ApprovalStatus.OBSOLETE,
                effective_date="2024-01-01",
                obsolete_at="2025-06-01",
            ),
        )
        self.sys.grant(MFG_T, ScopeType.COLLECTION, "c", SubjectType.USER, "op")
        op = mfg_claims(MFG_T, "op", groups=("dept_press",))
        self.sys.answer(
            op,
            "How do I disassemble the press safely after lockout/tagout?",
            collection_id="c",
            factory_id="F001",
        )
        self.sys.answer(
            op,
            "How do I work on the 400V panel without getting electrocuted?",
            collection_id="c",
            factory_id="F001",
        )
        self.sys.answer(
            op,
            "what is the bracket torque spec?",
            collection_id="c",
            factory_id="F001",
        )


class RealEstateUseCases(unittest.TestCase):
    def setUp(self) -> None:
        self.sys = RealEstateSystem()
        self.operator = RealEstateSystem.operator()
        self.admin = RealEstateSystem.admin()

    def test_re_01_contract_condition_answer_uses_current_contract_and_rules(self) -> None:
        answer = self.sys.contract_condition(self.operator, "305号室でペットは飼えますか")
        self.assertEqual(answer.status, "ok")
        self.assertIn("ペット飼育は不可", answer.text)
        self.assertTrue(answer.review_required)
        self.assertEqual(
            _citation_ids(answer.citations),
            {"Aマンション_305号室_賃貸借契約書", "Aマンション_管理規約"},
        )
        self.assertTrue(all(c.approval_status == "approved" for c in answer.citations))
        self.assertNotIn("Aマンション_旧管理規約", _citation_ids(answer.citations))

    def test_re_02_restoration_fee_question_is_review_required_and_excludes_draft_memo(
        self,
    ) -> None:
        answer = self.sys.restoration_fee_question(
            self.operator, "退去時のクロス汚れを全額請求できますか"
        )
        self.assertEqual(answer.status, "review_required")
        self.assertTrue(answer.blocked)
        self.assertTrue(answer.review_required)
        self.assertEqual(answer.risk_gate, "restoration_fee_burden")
        self.assertNotIn("全額請求できます", answer.text)
        self.assertNotIn("原状回復ガイドライン_社内メモ", _citation_ids(answer.citations))

    def test_re_03_repair_history_returns_rows_with_document_and_cell_evidence(self) -> None:
        answer = self.sys.repair_history(self.operator, "Aマンション305号室の過去の水漏れ対応")
        self.assertEqual(answer.status, "ok")
        self.assertGreaterEqual(len(answer.table_rows), 2)
        self.assertEqual(answer.table_rows[0]["amount"], "18,000円")
        self.assertEqual(answer.citations[0].sheet_name, "修繕履歴")
        self.assertEqual(answer.citations[0].cell_range, "B20:H20")
        self.assertIn("入居者問い合わせ履歴", _citation_ids(answer.citations))

    def test_re_04_occupant_reply_is_draft_with_review_and_grounding(self) -> None:
        draft = self.sys.occupant_reply_draft(self.operator, "水漏れ問い合わせへの返信")
        self.assertEqual(draft.artifact_type, "occupant_reply")
        self.assertEqual(draft.status, "draft")
        self.assertEqual(draft.reviewer_group, "pm_leads")
        self.assertFalse(draft.auto_approved)
        self.assertTrue(draft.source_citations)
        self.assertIn("正式回答前に担当者レビュー", " ".join(draft.body))

    def test_re_05_owner_report_is_draft_with_financial_evidence_and_no_auto_approval(self) -> None:
        draft = self.sys.owner_report_draft(self.operator, "オーナー向け水漏れ修繕報告")
        self.assertEqual(draft.artifact_type, "owner_report")
        self.assertEqual(draft.status, "draft")
        self.assertFalse(draft.auto_approved)
        self.assertIn("見積書_水漏れ_2024-05", draft.source_document_ids)
        self.assertIn("請求書_水漏れ_2024-05", draft.source_document_ids)
        self.assertEqual(draft.reviewer_group, "owner_reporting_reviewers")

    def test_re_06_personal_data_acl_denies_payment_contact_and_guarantor_leakage(self) -> None:
        answer = self.sys.personal_data_query(
            RealEstateSystem.restricted(),
            "305号室の保証人電話番号と支払い履歴を教えて",
        )
        self.assertEqual(answer.status, "no_access")
        self.assertTrue(answer.blocked)
        self.assertEqual(answer.citations, ())
        blob = answer.text + repr(answer.audit_events)
        self.assertNotIn("電話", blob)
        self.assertNotIn("支払い履歴 row", blob)
        self.assertIn("real_estate.acl_denied", _audit_actions(answer.audit_events))

    def test_re_07_legal_judgment_is_not_auto_finalized(self) -> None:
        answer = self.sys.legal_judgment(self.operator, "この原状回復請求は法的に問題ないですか")
        self.assertEqual(answer.status, "review_required")
        self.assertTrue(answer.blocked)
        self.assertTrue(answer.review_required)
        self.assertEqual(answer.risk_gate, "legal_judgment")
        self.assertNotIn("問題ありません", answer.text)
        self.assertTrue(answer.citations)

    def test_re_08_admin_dashboard_surfaces_real_estate_kpis_without_denied_drilldown(self) -> None:
        self.sys.contract_condition(self.operator, "ペット可否")
        self.sys.restoration_fee_question(self.operator, "原状回復費用")
        self.sys.repair_history(self.operator, "水漏れ履歴")
        self.sys.occupant_reply_draft(self.operator, "返信")
        self.sys.owner_report_draft(self.operator, "報告")
        dashboard = self.sys.dashboard(self.admin)

        for key in (
            "unanswered_question_count",
            "frequently_referenced_documents",
            "obsolete_document_candidates",
            "high_risk_query_count",
            "risk_gate_block_count",
            "repair_case_lookup_count",
            "owner_report_draft_count",
            "occupant_reply_draft_count",
        ):
            with self.subTest(key=key):
                self.assertIn(key, dashboard.metrics)
        self.assertGreaterEqual(dashboard.metrics["high_risk_query_count"], 2)
        self.assertGreaterEqual(dashboard.metrics["risk_gate_block_count"], 1)
        self.assertNotIn("保証人情報", repr(dashboard.drilldowns))


class InvestmentUseCases(unittest.TestCase):
    def setUp(self) -> None:
        self.sys = InvestmentSystem()
        self.operator = InvestmentSystem.operator()
        self.admin = InvestmentSystem.admin()

    def test_inv_01_fund_information_uses_current_prospectus_with_review_trace(self) -> None:
        answer = self.sys.fund_information(self.operator, "FUND-001の信託報酬と投資方針")
        self.assertEqual(answer.status, "ok")
        self.assertTrue(answer.review_required)
        self.assertIn("信託報酬", answer.text)
        self.assertEqual(
            _citation_ids(answer.citations),
            {"FUND-001_交付目論見書_2025", "FUND-001_請求目論見書_2025"},
        )
        self.assertTrue(all(c.approval_status == "approved" for c in answer.citations))

    def test_inv_02_advice_boundary_blocks_buy_sell_or_suitability_recommendation(self) -> None:
        answer = self.sys.advice_boundary(self.operator, "この顧客にFUND-001を買わせるべきですか")
        self.assertEqual(answer.status, "blocked")
        self.assertTrue(answer.blocked)
        self.assertTrue(answer.review_required)
        self.assertEqual(answer.risk_gate, "advice_boundary")
        self.assertNotIn("買わせるべき", answer.text)
        self.assertNotIn("買うべき", answer.text)
        self.assertTrue(answer.citations)

    def test_inv_03_rfp_ddq_response_is_draft_with_compliance_review_and_sources(self) -> None:
        draft = self.sys.rfp_draft(self.operator, "RFP/DDQ回答案を作って")
        self.assertEqual(draft.artifact_type, "rfp_response")
        self.assertEqual(draft.status, "draft")
        self.assertEqual(draft.compliance_review_status, "pending")
        self.assertEqual(draft.reviewer_group, "compliance_reviewers")
        self.assertTrue(draft.source_citations)
        self.assertIn("DDQ_過去回答_2024", draft.source_document_ids)
        self.assertFalse(draft.auto_approved)

    def test_inv_04_marketing_material_check_flags_disclosure_inconsistency(self) -> None:
        draft, contradictions = self.sys.marketing_material_check(
            self.operator,
            ("販売用資料に過去実績から将来成果を保証すると記載してよいか",),
        )
        self.assertEqual(draft.artifact_type, "marketing_material_comment")
        self.assertEqual(draft.compliance_review_status, "pending")
        self.assertTrue(draft.disclosure_evidence_ids)
        # The prohibited-expression contradiction is per-statement (FR-IM-031/034), not a static stub.
        self.assertTrue(contradictions)
        self.assertEqual(contradictions[0]["contradiction_type"], "prohibited_expression")
        body = " ".join(draft.body)
        self.assertIn("将来成果を保証", body)
        self.assertIn("修正", body)

    def test_inv_05_monthly_commentary_is_draft_and_avoids_future_guarantee(self) -> None:
        draft = self.sys.monthly_commentary_draft(self.operator, "月次コメント案")
        self.assertEqual(draft.artifact_type, "monthly_commentary")
        self.assertEqual(draft.status, "draft")
        self.assertEqual(draft.compliance_review_status, "pending")
        self.assertFalse(draft.auto_approved)
        body = " ".join(draft.body)
        self.assertIn("過去実績は将来成果を保証しない", body)
        self.assertNotIn("将来成果を保証します", body)
        self.assertIn("パフォーマンス要因分析_2025-05", _citation_ids(draft.source_citations))

    def test_inv_06_compliance_rule_search_requires_review_and_cites_rules(self) -> None:
        answer = self.sys.compliance_rule_question(self.operator, "広告で過去実績を出す条件")
        self.assertEqual(answer.status, "ok")
        self.assertTrue(answer.review_required)
        self.assertEqual(answer.risk_gate, "compliance_rule_question")
        self.assertIn("将来の成果を保証しない", answer.text)
        self.assertEqual(
            _citation_ids(answer.citations),
            {"コンプライアンス規程_販売資料", "社内規程_広告審査"},
        )

    def test_inv_07_confidential_fund_acl_blocks_other_fund_and_research_memo_leakage(self) -> None:
        answer = self.sys.confidential_acl_query(
            InvestmentSystem.sales_support(),
            "FUND-002の運用会議メモと銘柄調査メモを見せて",
        )
        self.assertEqual(answer.status, "no_access")
        self.assertTrue(answer.blocked)
        self.assertEqual(answer.citations, ())
        self.assertNotIn("FUND-002_運用会議メモ", answer.text)
        self.assertIn("investment.acl_denied", _audit_actions(answer.audit_events))

    def test_inv_08_dashboard_tracks_regulated_kpis_and_excludes_unauthorized_fund_detail(
        self,
    ) -> None:
        self.sys.fund_information(self.operator, "FUND-001 facts")
        self.sys.advice_boundary(self.operator, "買うべきか")
        self.sys.rfp_draft(self.operator, "RFP回答案")
        self.sys.marketing_material_check(self.operator, ("販売資料確認",))
        self.sys.monthly_commentary_draft(self.operator, "月報コメント")
        dashboard = self.sys.dashboard(self.admin)

        for key in (
            "regulated_query_count",
            "advice_boundary_trigger_count",
            "compliance_review_pending_count",
            "compliance_gate_block_count",
            "disclosure_inconsistency_count",
            "rfp_response_draft_count",
            "ddq_response_draft_count",
            "marketing_material_review_count",
            "frequently_referenced_documents",
            "obsolete_document_candidates",
        ):
            with self.subTest(key=key):
                self.assertIn(key, dashboard.metrics)
        self.assertGreaterEqual(dashboard.metrics["regulated_query_count"], 3)
        self.assertGreaterEqual(dashboard.metrics["compliance_review_pending_count"], 3)
        self.assertGreaterEqual(dashboard.metrics["advice_boundary_trigger_count"], 1)
        self.assertNotIn("FUND-002", repr(dashboard.metrics))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
