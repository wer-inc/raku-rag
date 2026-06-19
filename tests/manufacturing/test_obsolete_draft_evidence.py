"""T015 — SAFETY HARD GATE SC-MFG-011 (FR-MFG-006).

obsolete / draft documents must NEVER be used as PRIMARY evidence for an asserted answer:
 - evidence only in an OBSOLETE doc  => not primary evidence AND obsolete_warning present
   (reference-only with a warning; never the basis of an assertion).
 - evidence only in a DRAFT doc      => not formal evidence (no assertion built on it).
 - POSITIVE CONTROL: an APPROVED + effective doc answers normally with NO obsolete warning
   (so a degenerate "never answer / always warn" implementation CANNOT pass).

This is a DIFFERENT axis from SC-MFG-006 (T014, "approved citation missing on high-risk"): here the
queries are ordinary informational questions; the gate concerns the EVIDENCE STATE (obsolete/draft)
of what would otherwise be cited (FR-MFG-006).

Authoritative: spec FR-MFG-006, SC-MFG-011; contracts/mfg-openapi.md §A; contracts/mfg-interfaces.md
§4; quickstart S4; data-model §B/§E. Assertion style mirrors tests/security/test_acl_leak.py.

TDD: RED now because ``raku_rag.manufacturing.app.ManufacturingSystem`` is unimplemented.
"""
from __future__ import annotations

import unittest

from raku_rag.domain.models import ScopeType, SubjectType
from raku_rag.manufacturing.domain.metadata import ApprovalStatus
from tests.manufacturing.helpers import T, claims, fresh, mfg_meta


class TestObsoleteEvidenceNotPrimary(unittest.TestCase):
    """Evidence only in an OBSOLETE doc => not primary evidence AND obsolete_warning present."""

    def setUp(self) -> None:
        self.sys = fresh()
        # The ONLY doc that could answer is OBSOLETE.
        self.sys.ingest_manufacturing(
            tenant_id=T,
            collection_id="c",
            document_id="old_spec",
            text="The torque specification for the flange bolt is forty newton meters.",
            metadata=mfg_meta(
                tenant_id=T,
                document_id="old_spec",
                approval_status=ApprovalStatus.OBSOLETE,
                effective_date="2020-01-01",
                obsolete_at="2025-12-31",
                superseded_by="new_spec",
            ),
        )
        self.sys.grant(T, ScopeType.COLLECTION, "c", SubjectType.USER, "op")
        self.op = claims(T, "op")

    def test_obsolete_only_evidence_not_used_as_primary_and_warns(self) -> None:
        ans = self.sys.answer(self.op, "what is the torque specification for the flange bolt?")
        # Not used as primary evidence: an OBSOLETE doc must not back an asserted answer.
        self.assertNotEqual(
            ans.status, "ok",
            "obsolete-only evidence must NOT produce an asserted (ok) answer (SC-MFG-011)",
        )
        # When obsolete evidence is referenced at all, the warning is mandatory (FR-MFG-006).
        self.assertTrue(
            ans.obsolete_warning,
            "referencing an obsolete document requires obsolete_warning=True (FR-MFG-006)",
        )
        # The obsolete doc must not appear as a primary citation backing an assertion.
        for c in ans.citations:
            self.assertNotEqual(
                getattr(c, "approval_status", None), "obsolete",
                "an obsolete document must not be cited as primary evidence",
            )


class TestDraftEvidenceNotFormal(unittest.TestCase):
    """Evidence only in a DRAFT doc => not formal evidence (no assertion built on it)."""

    def setUp(self) -> None:
        self.sys = fresh()
        self.sys.ingest_manufacturing(
            tenant_id=T,
            collection_id="c",
            document_id="draft_spec",
            text="The torque specification for the flange bolt is forty newton meters.",
            metadata=mfg_meta(
                tenant_id=T,
                document_id="draft_spec",
                approval_status=ApprovalStatus.DRAFT,
                effective_date=None,
            ),
        )
        self.sys.grant(T, ScopeType.COLLECTION, "c", SubjectType.USER, "op")
        self.op = claims(T, "op")

    def test_draft_only_evidence_is_not_formal_basis(self) -> None:
        ans = self.sys.answer(self.op, "what is the torque specification for the flange bolt?")
        # A DRAFT doc is not formal evidence: it must not back an asserted answer (FR-MFG-006).
        self.assertNotEqual(
            ans.status, "ok",
            "draft-only evidence must NOT produce an asserted (ok) answer (FR-MFG-006/SC-MFG-011)",
        )
        # A draft must never be cited as approved formal evidence.
        for c in ans.citations:
            self.assertNotEqual(getattr(c, "approval_status", None), "approved")


class TestApprovedPositiveControl(unittest.TestCase):
    """POSITIVE CONTROL: an APPROVED + effective doc answers normally with NO obsolete warning."""

    def setUp(self) -> None:
        self.sys = fresh()
        self.sys.ingest_manufacturing(
            tenant_id=T,
            collection_id="c",
            document_id="approved_spec",
            text="The torque specification for the flange bolt is forty newton meters.",
            metadata=mfg_meta(
                tenant_id=T,
                document_id="approved_spec",
                approval_status=ApprovalStatus.APPROVED,
                effective_date="2026-01-10",
            ),
        )
        self.sys.grant(T, ScopeType.COLLECTION, "c", SubjectType.USER, "op")
        self.op = claims(T, "op")

    def test_approved_doc_answers_without_obsolete_warning(self) -> None:
        ans = self.sys.answer(self.op, "what is the torque specification for the flange bolt?")
        self.assertEqual(ans.status, "ok")
        self.assertTrue(ans.text)
        self.assertTrue(ans.citations)
        self.assertFalse(ans.obsolete_warning, "approved evidence must not raise an obsolete warning")
        self.assertEqual(ans.citations[0].approval_status, "approved")


if __name__ == "__main__":
    unittest.main()
