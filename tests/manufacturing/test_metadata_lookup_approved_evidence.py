"""Metadata-only high-risk lookups should answer from approved evidence.

The safety classifier must keep treating equipment/safety-tagged evidence as high-risk, but a neutral
"tell me about this equipment" lookup should not be blocked merely because obsolete or draft matches
also exist. The answer may assert only from approved+effective evidence.
"""

from __future__ import annotations

import unittest

from raku_rag.domain.models import ScopeType, SubjectType
from raku_rag.manufacturing.domain.metadata import ApprovalStatus, DocumentKind
from tests.manufacturing.helpers import T, claims, fresh, mfg_meta


class TestMetadataLookupUsesApprovedEvidence(unittest.TestCase):
    def test_equipment_overview_ignores_draft_and_obsolete_noise(self) -> None:
        sys = fresh()
        sys.ingest_manufacturing(
            tenant_id=T,
            collection_id="manuals",
            document_id="pw-e2e-approved",
            text="設備 PW-E2E-20260627 の点検周期は17日ごとです。",
            metadata=mfg_meta(
                tenant_id=T,
                document_id="pw-e2e-approved",
                approval_status=ApprovalStatus.APPROVED,
                effective_date="2026-01-10",
                document_kind=DocumentKind.WORK_INSTRUCTION,
                safety_category="routine_equipment",
                equipment_id="PW-E2E-20260627",
            ),
        )
        sys.ingest_manufacturing(
            tenant_id=T,
            collection_id="manuals",
            document_id="pw-e2e-obsolete",
            text="設備 PW-E2E-20260627 の旧版点検周期は5日ごとです。",
            metadata=mfg_meta(
                tenant_id=T,
                document_id="pw-e2e-obsolete",
                approval_status=ApprovalStatus.OBSOLETE,
                effective_date="2025-01-10",
                obsolete_at="2026-01-01",
                superseded_by="pw-e2e-approved",
                document_kind=DocumentKind.WORK_INSTRUCTION,
                safety_category="routine_equipment",
                equipment_id="PW-E2E-20260627",
            ),
        )
        sys.ingest_manufacturing(
            tenant_id=T,
            collection_id="manuals",
            document_id="pw-e2e-draft",
            text="設備 PW-E2E-20260627 はドラフトでは99日ごとです。",
            metadata=mfg_meta(
                tenant_id=T,
                document_id="pw-e2e-draft",
                approval_status=ApprovalStatus.DRAFT,
                effective_date=None,
                document_kind=DocumentKind.WORK_INSTRUCTION,
                safety_category="routine_equipment",
                equipment_id="PW-E2E-20260627",
            ),
        )
        sys.grant(T, ScopeType.COLLECTION, "manuals", SubjectType.USER, "op")

        ans = sys.answer(claims(T, "op"), "設備 PW-E2E-20260627 について教えて")

        self.assertTrue(ans.high_risk, "metadata-tagged evidence still classifies as high-risk")
        self.assertEqual(ans.status, "ok")
        self.assertIsNone(ans.safety_block_reason)
        self.assertTrue(ans.text)
        self.assertIn("17日", ans.text)
        self.assertNotIn("5日", ans.text)
        self.assertNotIn("99日", ans.text)
        self.assertTrue(ans.citations)
        self.assertEqual({c.approval_status for c in ans.citations}, {"approved"})
        self.assertTrue(ans.obsolete_warning, "obsolete matches are still surfaced as a warning")


if __name__ == "__main__":
    unittest.main()
