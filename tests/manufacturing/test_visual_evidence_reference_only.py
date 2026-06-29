"""Visual evidence stays reference-only until explicit promotion is implemented/enabled."""

from __future__ import annotations

import unittest
from datetime import date

from raku_rag.core.config import Settings
from raku_rag.domain.models import Citation, ExtractionSource, ScopeType, SubjectType
from raku_rag.manufacturing.app import ManufacturingSystem
from raku_rag.manufacturing.api.answer_ext import (
    ManufacturingCitation,
    _collapse_visual_page_citations,
)
from raku_rag.manufacturing.domain.metadata import (
    ApprovalStatus,
    DocumentKind,
    ManufacturingDocumentMetadata,
)
from raku_rag.manufacturing.domain.safety import HighRiskClassification, SafetyBlockReason
from raku_rag.manufacturing.safety.gate import ManufacturingSafetyGate
from raku_rag.manufacturing.safety.visual_verify import StaticVisualEvidenceVerifier
from tests.manufacturing.helpers import T, claims, mfg_meta

TODAY = date(2026, 6, 27)
PROMOTABLE_VISUAL_METADATA = {
    "primary_evidence_source": ExtractionSource.DETERMINISTIC_OCR.value,
    "extraction_source": ExtractionSource.DETERMINISTIC_OCR.value,
}


def _approved_meta(document_id: str = "visual_doc") -> ManufacturingDocumentMetadata:
    return ManufacturingDocumentMetadata(
        tenant_id=T,
        document_id=document_id,
        approval_status=ApprovalStatus.APPROVED,
        effective_date="2026-01-10",
        document_kind=DocumentKind.WORK_INSTRUCTION,
        safety_category="lockout_tagout",
        hazard_tags=("設備停止",),
    )


def _ingest_approved_visual_fixture(system: ManufacturingSystem) -> None:
    system._mvp.ingest_visual_fixture(
        tenant_id=T,
        collection_id="visual_manuals",
        document_id="visual_doc",
        image=(
            b"OCR: To stop the pump safely, press the emergency stop and lock out power.\n"
            b"caption: pump stop procedure panel"
        ),
    )
    for chunk, _ in system._mvp.store.iter_items():
        if chunk.document_id == "visual_doc":
            chunk.metadata["crop_uri"] = "s3://visual-crops/tenant/visual_doc/region.png"
    system.update_metadata(
        tenant_id=T,
        document_id="visual_doc",
        metadata=mfg_meta(
            tenant_id=T,
            document_id="visual_doc",
            approval_status=ApprovalStatus.APPROVED,
            effective_date="2026-01-10",
            document_kind=DocumentKind.WORK_INSTRUCTION,
            safety_category="lockout_tagout",
            hazard_tags=("設備停止",),
        ),
    )
    system.grant(T, ScopeType.COLLECTION, "visual_manuals", SubjectType.USER, "op")


def _answer_visual_stop(system: ManufacturingSystem):
    return system.answer(
        claims(T, "op"),
        "How do I stop the pump safely?",
        collection_id="visual_manuals",
        intent_hint="equipment_stop",
    )


class TestVisualEvidenceReferenceOnly(unittest.TestCase):
    def test_gate_does_not_count_visual_citation_when_promotion_flag_is_off(self) -> None:
        gate = ManufacturingSafetyGate(today=TODAY, visual_evidence_promotion=False)
        citation = Citation(
            kind="visual",
            document_id="visual_doc",
            source_id="camera_upload",
            version=1,
            retrieval_score=0.95,
            visual_evidence_verified=True,
            metadata=dict(PROMOTABLE_VISUAL_METADATA),
        )

        decision = gate.evaluate(
            HighRiskClassification(is_high_risk=True), [citation], [_approved_meta()]
        )

        self.assertTrue(decision.blocked)
        self.assertEqual(decision.safety_block_reason, SafetyBlockReason.APPROVED_CITATION_MISSING)

    def test_gate_counts_verified_visual_citation_only_when_promotion_flag_is_on(self) -> None:
        gate = ManufacturingSafetyGate(today=TODAY, visual_evidence_promotion=True)
        citation = Citation(
            kind="visual",
            document_id="visual_doc",
            source_id="camera_upload",
            version=1,
            retrieval_score=0.95,
            visual_evidence_verified=True,
            metadata=dict(PROMOTABLE_VISUAL_METADATA),
        )

        decision = gate.evaluate(
            HighRiskClassification(is_high_risk=True), [citation], [_approved_meta()]
        )

        self.assertFalse(decision.blocked)
        self.assertEqual(decision.approval_status_at_use, ApprovalStatus.APPROVED.value)

    def test_verified_visual_citation_without_promotable_provenance_still_fails(self) -> None:
        gate = ManufacturingSafetyGate(today=TODAY, visual_evidence_promotion=True)
        citation = Citation(
            kind="visual",
            document_id="visual_doc",
            source_id="camera_upload",
            version=1,
            retrieval_score=0.95,
            pixel_derived=True,
            visual_evidence_verified=True,
            metadata={"caption_source": "bedrock_claude_vision"},
        )

        decision = gate.evaluate(
            HighRiskClassification(is_high_risk=True), [citation], [_approved_meta()]
        )

        self.assertTrue(decision.blocked)
        self.assertEqual(decision.safety_block_reason, SafetyBlockReason.APPROVED_CITATION_MISSING)

    def test_text_citation_still_counts_when_visual_promotion_flag_is_off(self) -> None:
        gate = ManufacturingSafetyGate(today=TODAY, visual_evidence_promotion=False)
        citation = Citation(
            kind="text",
            document_id="text_doc",
            source_id="manual",
            version=1,
            retrieval_score=0.95,
        )

        decision = gate.evaluate(
            HighRiskClassification(is_high_risk=True),
            [citation],
            [_approved_meta("text_doc")],
        )

        self.assertFalse(decision.blocked)

    def test_high_risk_visual_fixture_blocks_in_manufacturing_answer_when_flag_is_off(self) -> None:
        system = ManufacturingSystem(settings=Settings(visual_evidence_promotion=False))
        _ingest_approved_visual_fixture(system)

        answer = _answer_visual_stop(system)

        self.assertTrue(answer.high_risk)
        self.assertEqual(answer.status, "insufficient_evidence")
        self.assertEqual(answer.safety_block_reason, "approved_citation_missing")
        self.assertEqual(answer.used_chunks, ())

    def test_high_risk_visual_fixture_promotes_with_real_crop_and_quorum_when_flag_is_on(
        self,
    ) -> None:
        system = ManufacturingSystem(settings=Settings(visual_evidence_promotion=True))
        system._mvp.answer_service._visual_verifiers = (
            StaticVisualEvidenceVerifier("bedrock_claude", "bedrock", "claude-sonnet"),
            StaticVisualEvidenceVerifier("vertex_gemini", "vertex", "gemini-pro"),
        )
        _ingest_approved_visual_fixture(system)

        answer = _answer_visual_stop(system)

        self.assertTrue(answer.high_risk)
        self.assertEqual(answer.status, "ok")
        self.assertTrue(answer.citations[0].visual_evidence_verified)
        entries = system.audit.read_all(claims(T, "op"))
        visual_evidence = entries[-2].client_metadata["visual_evidence"]
        self.assertTrue(visual_evidence[0]["promoted"])
        self.assertEqual(visual_evidence[0]["approval_status_at_use"], "approved")
        self.assertIn(visual_evidence[0]["grounding_method"], {"ocr_subset", "ocr_verbatim"})
        self.assertEqual(visual_evidence[0]["quorum"], 2)
        self.assertEqual(len(visual_evidence[0]["verifiers"]), 3)

    def test_denied_visual_promotion_is_audited_without_raw_visual_payload(self) -> None:
        system = ManufacturingSystem(settings=Settings(visual_evidence_promotion=True))
        _ingest_approved_visual_fixture(system)

        answer = _answer_visual_stop(system)

        self.assertEqual(answer.status, "insufficient_evidence")
        self.assertEqual(answer.safety_block_reason, "approved_citation_missing")
        entries = system.audit.read_all(claims(T, "op"))
        visual_evidence = entries[-2].client_metadata["visual_evidence"]
        self.assertFalse(visual_evidence[0]["promoted"])
        self.assertEqual(visual_evidence[0]["approval_status_at_use"], "approved")
        self.assertIn(visual_evidence[0]["grounding_method"], {"ocr_subset", "ocr_verbatim"})
        self.assertEqual(visual_evidence[0]["quorum"], 2)
        reason_codes = {verdict["reason_code"] for verdict in visual_evidence[0]["verifiers"]}
        self.assertIn("verifier_quorum_not_met", reason_codes)
        serialized = str(visual_evidence)
        self.assertNotIn("emergency stop", serialized)
        self.assertNotIn("pump stop procedure", serialized)
        self.assertNotIn("s3://", serialized)

    def test_verified_page_visual_citation_replaces_same_page_line_citations(self) -> None:
        line = ManufacturingCitation(
            kind="visual",
            document_id="visual_doc",
            source_id="camera_upload",
            version=1,
            retrieval_score=0.91,
            chunk_id="line-1",
            asset_id="asset-1",
            page_number=1,
            region_id="line-1",
            pixel_derived=True,
            visual_evidence_verified=False,
            metadata=dict(PROMOTABLE_VISUAL_METADATA, region_type="line"),
        )
        page = ManufacturingCitation(
            kind="visual",
            document_id="visual_doc",
            source_id="camera_upload",
            version=1,
            retrieval_score=0.95,
            chunk_id="page-1",
            asset_id="asset-1",
            page_number=1,
            region_id="page-1",
            pixel_derived=True,
            visual_evidence_verified=True,
            metadata=dict(
                PROMOTABLE_VISUAL_METADATA,
                page_aggregate=True,
                region_type="page",
            ),
        )
        other_page_line = ManufacturingCitation(
            kind="visual",
            document_id="visual_doc",
            source_id="camera_upload",
            version=1,
            retrieval_score=0.89,
            chunk_id="line-2",
            asset_id="asset-1",
            page_number=2,
            region_id="line-2",
            pixel_derived=True,
            visual_evidence_verified=False,
            metadata=dict(PROMOTABLE_VISUAL_METADATA, region_type="line"),
        )

        collapsed = _collapse_visual_page_citations((line, page, other_page_line))

        self.assertEqual(tuple(c.chunk_id for c in collapsed), ("page-1", "line-2"))


if __name__ == "__main__":
    unittest.main()
