"""T039 — SAFETY HARD GATE SC-MFG-007 (Hard Rule 1; FR-MFG-010/010a; data-model §F; quickstart S6.5).

This is an ABSOLUTE gate (loop-engineering §3 mechanism-pin). The central manufacturing safety
invariant: AI-generated artifacts are ALWAYS created ``status=draft`` and MUST NOT become
approved/confirmed without an explicit human REVIEWER action. ``created_by=ai`` can NEVER self-approve.
FAQ is treated exactly like every other draft. ``approved`` is reachable ONLY via a reviewer.

Mechanism pinned RIGOROUSLY (do NOT weaken in stage 2):
 (1) GENERATOR ALWAYS DRAFT — every generated kind (checklist/trouble_report/quality_report/
     training/FAQ) is created ``status==draft`` AND ``created_by=='ai'``.
 (2) AI CANNOT SELF-APPROVE — driving an ai-created artifact to approved WITHOUT a reviewer (direct
     status mutation, or a review call carrying no reviewer_id) MUST be rejected: the artifact stays
     ``draft`` (or the call raises). We ASSERT the rejection — this is load-bearing, not advisory.
 (3) REVIEWER REQUIRED — ``approved`` is reachable ONLY through the review workflow with a reviewer_id;
     the resulting approval is attributable to that reviewer.
 (4) POSITIVE CONTROL — a reviewer CAN approve a draft => status becomes ``approved`` with the reviewer
     recorded. (Blocks a degenerate "approval is always impossible" implementation from passing.)
 (5) FAQ PARITY — a FAQ draft is draft-only just like the others (not auto-published, G1).

Authoritative: spec Hard Rule 1, FR-MFG-010/010a, SC-MFG-007; contracts/mfg-openapi.md §D +
"安全・監査"; contracts/mfg-interfaces.md §6 (DraftGenerator/ReviewWorkflow); data-model §F; quickstart
S6. Assertion style mirrors tests/security/test_acl_leak.py and tests/manufacturing/test_safety_gate.py.

TDD: RED now because ``raku_rag.manufacturing.app.ManufacturingSystem`` has no draft entrypoints yet
(missing-impl) — NOT an unrelated import error.
"""

from __future__ import annotations

import unittest

from raku_rag.manufacturing.domain.draft import CreatedBy, DraftStatus, DraftType
from tests.manufacturing.helpers import T, claims, fresh

ALL_KINDS = (
    DraftType.CHECKLIST,
    DraftType.TROUBLE_REPORT,
    DraftType.QUALITY_REPORT,
    DraftType.TRAINING,
    DraftType.FAQ,
)


def _status_value(artifact) -> str:
    return getattr(artifact.status, "value", artifact.status)


def _created_by_value(artifact) -> str | None:
    cb = artifact.created_by
    return getattr(cb, "value", cb)


class TestGeneratorAlwaysDraft(unittest.TestCase):
    """(1) Every generated kind is created status==draft AND created_by==ai."""

    def setUp(self) -> None:
        self.sys = fresh()
        self.author = claims(T, "author")

    def test_every_generated_kind_is_draft_and_ai_authored(self) -> None:
        for kind in ALL_KINDS:
            with self.subTest(kind=kind):
                art = self.sys.generate_draft(principal=self.author, kind=kind)
                self.assertEqual(
                    _status_value(art),
                    DraftStatus.DRAFT.value,
                    f"generated {kind.value} MUST be status=draft (Hard Rule 1, SC-MFG-007)",
                )
                self.assertEqual(
                    _created_by_value(art),
                    CreatedBy.AI.value,
                    f"generated {kind.value} MUST be created_by=ai",
                )
                # Defensive: a generator must never emit an already-approved artifact.
                self.assertNotEqual(_status_value(art), DraftStatus.APPROVED.value)


class TestAiCannotSelfApprove(unittest.TestCase):
    """(2) An ai-created artifact CANNOT reach approved without a reviewer. ASSERT the rejection."""

    def setUp(self) -> None:
        self.sys = fresh()
        self.author = claims(T, "author")
        self.art = self.sys.generate_draft(principal=self.author, kind=DraftType.CHECKLIST)
        # Precondition: it really is an ai-authored draft.
        self.assertEqual(_status_value(self.art), DraftStatus.DRAFT.value)
        self.assertEqual(_created_by_value(self.art), CreatedBy.AI.value)

    def test_review_without_reviewer_is_rejected(self) -> None:
        """A review/approve call carrying NO reviewer (reviewer=None) MUST NOT yield approved."""
        approved_leaked = False
        try:
            result = self.sys.review_draft(
                tenant_id=T,
                artifact_id=self.art.artifact_id,
                reviewer=None,  # no human reviewer => self-approve attempt
                decision="approved",
            )
            # If the impl chose to RETURN rather than RAISE, it MUST NOT have approved.
            approved_leaked = _status_value(result) == DraftStatus.APPROVED.value
        except (ValueError, PermissionError, TypeError):
            # Rejection by raising is the expected, acceptable behaviour.
            pass
        self.assertFalse(
            approved_leaked,
            "AI self-approve (review with no reviewer) MUST be rejected (SC-MFG-007 = 0)",
        )
        # And the persisted artifact must remain a draft regardless of the attempt.
        stored = self.sys.get_draft(T, self.art.artifact_id)
        self.assertEqual(
            _status_value(stored),
            DraftStatus.DRAFT.value,
            "after a no-reviewer approve attempt the artifact MUST still be draft (SC-MFG-007)",
        )

    def test_direct_status_mutation_to_approved_does_not_take_effect(self) -> None:
        """Mutating the dataclass status directly MUST NOT be honored by the system of record.

        The dataclass field is writable, but the system MUST treat approval as reachable ONLY through
        the reviewer workflow: the persisted/system-of-record artifact stays draft (no auto-approve).
        """
        # Attempt the crude bypass a careless caller might try.
        try:
            self.art.status = DraftStatus.APPROVED
        except Exception:  # noqa: BLE001 - frozen-or-not is impl detail; the gate is below.
            pass
        stored = self.sys.get_draft(T, self.art.artifact_id)
        self.assertEqual(
            _status_value(stored),
            DraftStatus.DRAFT.value,
            "direct status mutation MUST NOT make the system-of-record artifact approved "
            "without a reviewer (Hard Rule 1, SC-MFG-007)",
        )
        self.assertIsNone(
            stored.reviewer_id,
            "an approval with no reviewer is never attributable and must not exist",
        )


class TestReviewerRequiredForApproved(unittest.TestCase):
    """(3) approved is reachable ONLY through a reviewer, and is attributable to that reviewer."""

    def setUp(self) -> None:
        self.sys = fresh()
        self.author = claims(T, "author")
        self.art = self.sys.generate_draft(principal=self.author, kind=DraftType.TRAINING)
        self.sys.assign_reviewer(tenant_id=T, artifact_id=self.art.artifact_id, reviewer_id="rev_9")

    def test_approved_is_attributable_to_the_reviewer(self) -> None:
        reviewer = claims(T, "rev_9", roles=("reviewer",))
        approved = self.sys.review_draft(
            tenant_id=T,
            artifact_id=self.art.artifact_id,
            reviewer=reviewer,
            decision="approved",
            comment="ok",
        )
        self.assertEqual(_status_value(approved), DraftStatus.APPROVED.value)
        # The approval is attributable to the human reviewer who made it.
        self.assertEqual(approved.reviewer_id, "rev_9")
        self.assertTrue(approved.reviewed_at, "an approval must record when the reviewer decided")
        self.assertEqual(approved.approval_decision, "approved")
        # created_by remains 'ai' (provenance is not rewritten); approval comes from the reviewer.
        self.assertEqual(_created_by_value(approved), CreatedBy.AI.value)


class TestReviewerCanApprovePositiveControl(unittest.TestCase):
    """(4) POSITIVE CONTROL — a reviewer CAN approve (blocks "approval always impossible")."""

    def test_reviewer_can_approve_draft(self) -> None:
        sys = fresh()
        art = sys.generate_draft(principal=claims(T, "author"), kind=DraftType.QUALITY_REPORT)
        sys.assign_reviewer(tenant_id=T, artifact_id=art.artifact_id, reviewer_id="rev_pc")
        approved = sys.review_draft(
            tenant_id=T,
            artifact_id=art.artifact_id,
            reviewer=claims(T, "rev_pc", roles=("reviewer",)),
            decision="approved",
        )
        self.assertEqual(
            _status_value(approved),
            DraftStatus.APPROVED.value,
            "a reviewer MUST be able to approve a draft (positive control)",
        )
        self.assertEqual(approved.reviewer_id, "rev_pc")
        # And the persisted record reflects the approval done by the reviewer.
        stored = sys.get_draft(T, art.artifact_id)
        self.assertEqual(_status_value(stored), DraftStatus.APPROVED.value)
        self.assertEqual(stored.reviewer_id, "rev_pc")


class TestFaqParity(unittest.TestCase):
    """(5) FAQ PARITY — a FAQ draft is draft-only just like the others (not auto-published, G1)."""

    def setUp(self) -> None:
        self.sys = fresh()
        self.author = claims(T, "author")

    def test_faq_is_created_draft_and_not_auto_published(self) -> None:
        faq = self.sys.generate_draft(principal=self.author, kind=DraftType.FAQ)
        self.assertEqual(faq.type, DraftType.FAQ)
        self.assertEqual(
            _status_value(faq),
            DraftStatus.DRAFT.value,
            "FAQ MUST be created status=draft (treated like every other draft, G1)",
        )
        self.assertEqual(_created_by_value(faq), CreatedBy.AI.value)

    def test_faq_cannot_self_approve_without_reviewer(self) -> None:
        faq = self.sys.generate_draft(principal=self.author, kind=DraftType.FAQ)
        approved_leaked = False
        try:
            result = self.sys.review_draft(
                tenant_id=T,
                artifact_id=faq.artifact_id,
                reviewer=None,
                decision="approved",
            )
            approved_leaked = _status_value(result) == DraftStatus.APPROVED.value
        except (ValueError, PermissionError, TypeError):
            pass
        self.assertFalse(
            approved_leaked,
            "a FAQ must not be auto-approved without a reviewer (FAQ parity, SC-MFG-007/G1)",
        )
        stored = self.sys.get_draft(T, faq.artifact_id)
        self.assertEqual(_status_value(stored), DraftStatus.DRAFT.value)

    def test_faq_reaches_approved_only_via_reviewer(self) -> None:
        faq = self.sys.generate_draft(principal=self.author, kind=DraftType.FAQ)
        self.sys.assign_reviewer(tenant_id=T, artifact_id=faq.artifact_id, reviewer_id="faq_rev")
        approved = self.sys.review_draft(
            tenant_id=T,
            artifact_id=faq.artifact_id,
            reviewer=claims(T, "faq_rev", roles=("reviewer",)),
            decision="approved",
        )
        self.assertEqual(_status_value(approved), DraftStatus.APPROVED.value)
        self.assertEqual(approved.reviewer_id, "faq_rev")


if __name__ == "__main__":
    unittest.main()
