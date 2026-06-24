"""P1-1 — answer-service manufacturing answer serialization on the deployed boundary.

In-process (server module import + MvpSystem with persisted Document.metadata): the overlay the
`/internal/manufacturing/answer` route builds produces a ManufacturingAnswer, and
`_manufacturing_answer_json` serializes the safety extension (nested under `manufacturing`, GAP-M02),
including the high-risk approved-citation block (GAP-S3) and approval provenance on citations.
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

from raku_rag.domain.models import IdentityClaims, ScopeType, SubjectType
from raku_rag.manufacturing.domain.metadata import (
    ApprovalStatus,
    DocumentKind,
    ManufacturingDocumentMetadata,
)
from raku_rag.manufacturing.ingestion.metadata_enrichment import MFG_META_KEY
# Build the answer service from the wiring module directly: the deployed answer-service route now
# goes through the AUDITED manufacturing_system.answer path (FR-MFG-021) and no longer imports the
# build_manufacturing_answer_service overlay, so this serialization test sources it from wiring.
from raku_rag.manufacturing.wiring import build_manufacturing_answer_service

ROOT = Path(__file__).resolve().parents[2]
T = "tenant_mfg"
LOCKOUT = (
    "To disassemble the press, first stop the machine, apply lockout tagout, and release the stored "
    "hydraulic pressure before removing any guard."
)
HIGH_RISK = "How do I disassemble the press safely?"


def _load_server():
    path = ROOT / "apps/answer-service/server.py"
    spec = importlib.util.spec_from_file_location("answer_service_server", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _meta(document_id, status, effective):
    return ManufacturingDocumentMetadata(
        tenant_id=T,
        document_id=document_id,
        approval_status=status,
        effective_date=effective,
        document_kind=DocumentKind.WORK_INSTRUCTION,
        safety_category="lockout_tagout",
        hazard_tags=("設備停止", "分解", "高圧"),
    )


class TestManufacturingAnswerEndpoint(unittest.TestCase):
    def setUp(self) -> None:
        from raku_rag.app import MvpSystem

        self.srv = _load_server()
        self.sys = MvpSystem()
        self.sys.grant(T, ScopeType.COLLECTION, "c", SubjectType.USER, "op")
        self.op = IdentityClaims(tenant_id=T, user_id="op")

    def _ingest(self, document_id, status, effective):
        self.sys.ingest_text(tenant_id=T, collection_id="c", document_id=document_id, text=LOCKOUT)
        self.sys.registry.get(T, document_id).metadata[MFG_META_KEY] = _meta(
            document_id, status, effective
        )

    def _answer_json(self, query):
        service = build_manufacturing_answer_service(self.sys)
        profile = self.sys.profiles.resolve("c")
        ans, *_ = service.answer(self.op, query, profile)
        return self.srv._manufacturing_answer_json(ans)

    def test_high_risk_without_approved_serializes_block(self) -> None:
        self._ingest("draft_proc", ApprovalStatus.DRAFT, None)
        out = self._answer_json(HIGH_RISK)
        self.assertEqual(out["status"], "insufficient_evidence")
        self.assertTrue(out["manufacturing"]["high_risk"])
        self.assertEqual(out["manufacturing"]["safety_block_reason"], "approved_citation_missing")

    def test_high_risk_with_approved_serializes_answer_with_provenance(self) -> None:
        self._ingest("approved_proc", ApprovalStatus.APPROVED, "2026-01-10")
        out = self._answer_json(HIGH_RISK)
        self.assertEqual(out["status"], "ok")
        self.assertTrue(out["manufacturing"]["high_risk"])
        self.assertTrue(out["manufacturing"]["requires_onsite_confirmation"])
        self.assertIsNotNone(out["manufacturing"]["notice"])
        self.assertEqual(out["citations"][0]["approval_status"], "approved")


if __name__ == "__main__":
    unittest.main()
