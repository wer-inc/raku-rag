"""T012 — POST /v1/answer manufacturing-extension SHAPE contract (contracts/mfg-openapi.md §A).

This is the response-shape contract for the 001 ``/v1/answer`` extension. It does NOT re-test 001
behaviour; it asserts that the manufacturing answer ADDS the extension fields (additive only, never
changing 001 field meaning) and that citations carry approval provenance.

Authoritative: contracts/mfg-openapi.md §A (res 200 added fields), data-model.md §B/§E,
FR-MFG-004/005/006/007/015/030.

TDD: RED now because ``raku_rag.manufacturing.app.ManufacturingSystem`` is unimplemented.
"""

from __future__ import annotations

import unittest

from raku_rag.domain.models import ScopeType, SubjectType
from tests.manufacturing.helpers import T, claims, fresh, mfg_meta


class TestAnswerExtensionShape(unittest.TestCase):
    def setUp(self) -> None:
        self.sys = fresh()
        # An APPROVED + effective manual whose body grounds a normal (non-high-risk) question.
        self.sys.ingest_manufacturing(
            tenant_id=T,
            collection_id="c",
            document_id="manual1",
            text="The conveyor motor lubrication interval is every ninety days under normal load.",
            metadata=mfg_meta(tenant_id=T, document_id="manual1"),
        )
        self.sys.grant(T, ScopeType.COLLECTION, "c", SubjectType.USER, "op")
        self.op = claims(T, "op")

    def test_answer_carries_manufacturing_extension_fields(self) -> None:
        ans = self.sys.answer(self.op, "what is the conveyor motor lubrication interval?")
        # 001 base status vocabulary preserved (extension is additive, not a new status set).
        self.assertIn(ans.status, ("ok", "insufficient_evidence"))
        # Manufacturing extension fields exist with the documented types (contracts §A).
        self.assertIsInstance(ans.high_risk, bool)
        self.assertIsInstance(ans.high_risk_reason_codes, tuple)
        self.assertIsInstance(ans.obsolete_warning, bool)
        self.assertIsInstance(ans.requires_onsite_confirmation, bool)
        # safety_block_reason is a single normalized code or None (mutually exclusive, FR-MFG-030).
        self.assertIn(
            ans.safety_block_reason,
            (None, "approved_citation_missing", "insufficient_evidence", "other_block"),
        )

    def test_status_ok_implies_no_block_reason(self) -> None:
        # When the answer is asserted (status ok), there is no safety block reason (FR-MFG-030).
        ans = self.sys.answer(self.op, "what is the conveyor motor lubrication interval?")
        if ans.status == "ok":
            self.assertIsNone(ans.safety_block_reason)

    def test_citation_carries_approval_provenance(self) -> None:
        ans = self.sys.answer(self.op, "what is the conveyor motor lubrication interval?")
        self.assertEqual(ans.status, "ok", "approved+effective manual should answer normally (S2)")
        self.assertTrue(ans.citations, "must return citations")
        c = ans.citations[0]
        # Base 001 citation fields preserved.
        self.assertEqual(c.kind, "text")
        self.assertEqual(c.document_id, "manual1")
        # Manufacturing-required additions on each citation (FR-MFG-004, contracts §A / openapi §A).
        self.assertEqual(c.approval_status, "approved")
        self.assertEqual(c.effective_date, "2026-01-10")
        self.assertEqual(c.approval_source, "imported")


if __name__ == "__main__":
    unittest.main()
