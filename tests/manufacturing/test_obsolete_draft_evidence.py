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


class TestObsoletePrimaryWithUnrelatedApprovedCoexisting(unittest.TestCase):
    """MULTI-DOC obsolete-as-PRIMARY-citation gap (FR-MFG-006 / SC-MFG-011) — the T066 capstone class.

    The three cases above pin the SINGLE-doc axis: when the obsolete/draft doc is the ONLY candidate,
    the SafetyGate pre-gate already blocks (its ``has_usable_primary`` is False). But the T066 capstone
    revealed a SHARPER bug the isolated single-doc gate MISSED: when an UNRELATED approved doc *coexists*
    as a weak candidate, the pre-gate's ``has_usable_primary`` becomes True (satisfied by that approved
    doc), so the SafetyGate does NOT block — yet the reused 001 answer path still ranks the OBSOLETE doc
    as the TOP (primary) citation and asserts. The obsolete doc would then be the real basis of the
    assertion, violating the gate's documented "an obsolete document is NEVER primary evidence" invariant.

    ``ManufacturingAnswerService.answer`` (api/answer_ext.py) closes this: on a non-high-risk ``ok``
    answer whose PRIMARY (top) citation is obsolete and with NO approved+effective doc among the actually
    CITED evidence, it demotes to ``insufficient_evidence`` (reference-only + the mandatory obsolete
    warning). This gate test reproduces the multi-doc scenario DETERMINISTICALLY and pins that demote, so
    the bug class is caught HERE too — not only end-to-end in the capstone.
    """

    # Query whose distinctive tokens (coolant/flow/setpoint/grinder/spindle/legacy) are all carried by
    # the OBSOLETE doc, so deterministic bag-of-words cosine ranks it #1 (the primary candidate). The
    # generic token 'rate' is shared ONLY with the unrelated approved doc (see below).
    QUERY = "what is the legacy coolant flow setpoint rate for the grinder spindle?"

    def setUp(self) -> None:
        self.sys = fresh()
        # The ONLY on-topic (coolant) evidence is OBSOLETE. TWO strongly-overlapping sentences so the
        # deterministic extractive answer path fills BOTH of its sentence slots from this doc alone —
        # the unrelated approved doc's single weak sentence therefore never enters the answer text, so
        # the approved doc is NOT among the actually-cited evidence (only surveyed as a candidate).
        self.sys.ingest_manufacturing(
            tenant_id=T,
            collection_id="c",
            document_id="obsolete_coolant",
            text=(
                "The legacy coolant flow setpoint for the grinder spindle is eight liters per minute. "
                "This legacy coolant setpoint governs the grinder spindle flow during finishing."
            ),
            metadata=mfg_meta(
                tenant_id=T,
                document_id="obsolete_coolant",
                approval_status=ApprovalStatus.OBSOLETE,
                effective_date="2020-01-01",
                obsolete_at="2025-12-31",
                superseded_by="new_coolant_spec",
            ),
        )
        # An UNRELATED APPROVED + effective doc that COEXISTS as a weak candidate: it shares ONLY the
        # generic query token 'rate', so its cosine clears the groundedness pre-gate threshold (it is a
        # usable-primary candidate => the SafetyGate's has_usable_primary is True and it does NOT block)
        # WITHOUT outranking the obsolete doc and WITHOUT sharing any token with the obsolete answer
        # text (so it is never cited). This is the multi-doc noise the single-doc gate could not model.
        self.sys.ingest_manufacturing(
            tenant_id=T,
            collection_id="c",
            document_id="approved_unrelated",
            text="The conveyor motor lubrication rate schedule covers routine greasing intervals.",
            metadata=mfg_meta(
                tenant_id=T,
                document_id="approved_unrelated",
                approval_status=ApprovalStatus.APPROVED,
                effective_date="2026-01-10",
            ),
        )
        self.sys.grant(T, ScopeType.COLLECTION, "c", SubjectType.USER, "op")
        self.op = claims(T, "op")

    def test_obsolete_primary_with_unrelated_approved_is_not_an_asserted_answer(self) -> None:
        from raku_rag.manufacturing.domain.safety import SafetyBlockReason

        ans = self.sys.answer(self.op, self.QUERY)

        # The approved doc makes has_usable_primary True, so this is NOT caught by the single-doc
        # pre-gate — it must be caught by the answer-path demote. An obsolete top citation must NEVER
        # back an asserted (ok) answer (FR-MFG-006 / SC-MFG-011).
        self.assertNotEqual(
            ans.status,
            "ok",
            "an obsolete PRIMARY citation must NOT produce an asserted (ok) answer even when an "
            "unrelated approved doc coexists as a weak candidate (FR-MFG-006/SC-MFG-011)",
        )
        # Demoted to reference-only: insufficient_evidence with the normalized block reason.
        self.assertEqual(ans.status, "insufficient_evidence")
        self.assertEqual(ans.safety_block_reason, SafetyBlockReason.INSUFFICIENT_EVIDENCE.value)

        # Referencing obsolete material keeps the mandatory warning (consistent with the cases above).
        self.assertTrue(
            ans.obsolete_warning,
            "referencing an obsolete document requires obsolete_warning=True (FR-MFG-006)",
        )

        # No obsolete document is the primary basis of an asserted answer: the demote returns empty
        # citations/text, so the obsolete doc is reference-only and never cited as primary evidence.
        self.assertFalse(ans.text, "a demoted answer must not assert text grounded on obsolete evidence")
        self.assertEqual(ans.used_chunks, (), "a demoted answer must use no chunks as its basis")
        for c in ans.citations:
            self.assertNotEqual(
                getattr(c, "approval_status", None),
                "obsolete",
                "an obsolete document must never be the primary citation behind an asserted answer",
            )


if __name__ == "__main__":
    unittest.main()
