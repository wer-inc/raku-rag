"""T038 — Draft generation / review SHAPE contract (US4; contracts/mfg-openapi.md §D).

Response-shape contract for the NEW manufacturing draft endpoints (POST /v1/manufacturing/drafts,
.../assign, .../review, GET .../{id}). It asserts the DraftArtifact-shaped results of the in-memory
``ManufacturingSystem`` draft entrypoints carry the documented fields and that a generated artifact
is ``status=draft`` on creation with the reviewer-transition fields present after assign/review.

This is the SHAPE axis only; the load-bearing safety behaviour (draft-only, no AI self-approve,
reviewer-required) is pinned by T039 (test_draft_only.py), and the citation/groundedness content by
T040 (test_draft_generation.py).

Entrypoint contract the stage-2 ManufacturingSystem must satisfy (analog of .answer/.search; mirrors
contracts/mfg-openapi.md §D and contracts/mfg-interfaces.md §6 — DraftGenerator/ReviewWorkflow):

  generate_draft(*, principal, kind, context_citations=(), source_document_ids=(),
                 template_id=None, collection_id=None, manufacturing_filters=None) -> DraftArtifact
      POST /v1/manufacturing/drafts. ALWAYS returns status=draft, created_by=ai, with
      source_citations / source_document_ids / template_id / created_at / audit_log_ref provenance
      (FR-MFG-010/010b). kind ∈ {checklist, trouble_report, quality_report, training, faq}.
  get_draft(tenant_id, artifact_id) -> DraftArtifact | None
      GET /v1/manufacturing/drafts/{artifact_id}.
  assign_reviewer(*, tenant_id, artifact_id, reviewer_id=None, reviewer_group=None,
                  reviewer_role=None) -> DraftArtifact
      POST .../assign => status=in_review, assigned_at + reviewer attribution recorded (FR-MFG-010a).
  review_draft(*, tenant_id, artifact_id, reviewer, decision, comment=None) -> DraftArtifact
      POST .../review; decision ∈ {approved, rejected, archived}; reviewer-only (FR-MFG-010a).

TDD: RED now because ``raku_rag.manufacturing.app.ManufacturingSystem`` has no draft entrypoints yet
(missing-impl), NOT an unrelated import error. Assertion style mirrors tests/manufacturing/*.
"""

from __future__ import annotations

import unittest

from raku_rag.manufacturing.domain.draft import DraftStatus, DraftType
from tests.manufacturing.helpers import T, claims, fresh

# The five generated kinds (contracts §D; data-model §F). FAQ is included like the others.
ALL_KINDS = (
    DraftType.CHECKLIST,
    DraftType.TROUBLE_REPORT,
    DraftType.QUALITY_REPORT,
    DraftType.TRAINING,
    DraftType.FAQ,
)


def _status_value(artifact) -> str:
    """The artifact.status as a normalized string ('draft' | 'in_review' | ...)."""
    return getattr(artifact.status, "value", artifact.status)


class TestGenerateResponseShape(unittest.TestCase):
    """POST /v1/manufacturing/drafts response shape: status=draft + provenance on creation."""

    def setUp(self) -> None:
        self.sys = fresh()
        self.author = claims(T, "author")

    def test_generate_returns_draft_artifact_with_provenance_fields(self) -> None:
        art = self.sys.generate_draft(
            principal=self.author,
            kind=DraftType.CHECKLIST,
            source_document_ids=("doc_1", "doc_2"),
            template_id="tpl_checklist_v1",
        )
        # Identity / typing.
        self.assertEqual(art.tenant_id, T)
        self.assertTrue(art.artifact_id, "generated artifact must have an artifact_id")
        self.assertEqual(art.type, DraftType.CHECKLIST)
        # status=draft on creation (contracts §D res 200 always status:"draft").
        self.assertEqual(_status_value(art), DraftStatus.DRAFT.value)
        # Generation provenance / audit trail (FR-MFG-010b).
        self.assertEqual(getattr(art.created_by, "value", art.created_by), "ai")
        self.assertEqual(art.template_id, "tpl_checklist_v1")
        self.assertIn("doc_1", art.source_document_ids)
        self.assertIn("doc_2", art.source_document_ids)
        self.assertTrue(art.created_at, "created_at provenance must be set")
        self.assertTrue(
            art.audit_log_ref, "audit_log_ref must reference the audit entry (FR-MFG-021)"
        )

    def test_every_kind_is_generated_as_draft(self) -> None:
        for kind in ALL_KINDS:
            with self.subTest(kind=kind):
                art = self.sys.generate_draft(principal=self.author, kind=kind)
                self.assertEqual(art.type, kind)
                self.assertEqual(
                    _status_value(art),
                    DraftStatus.DRAFT.value,
                    f"generated {kind.value} must be created status=draft (contracts §D)",
                )

    def test_generated_draft_is_retrievable(self) -> None:
        art = self.sys.generate_draft(principal=self.author, kind=DraftType.FAQ)
        got = self.sys.get_draft(T, art.artifact_id)
        self.assertIsNotNone(
            got, "generated draft must be retrievable via get_draft (GET .../{id})"
        )
        self.assertEqual(got.artifact_id, art.artifact_id)
        self.assertEqual(got.type, DraftType.FAQ)


class TestAssignResponseShape(unittest.TestCase):
    """POST .../assign response shape: status=in_review + reviewer-transition fields present."""

    def setUp(self) -> None:
        self.sys = fresh()
        self.author = claims(T, "author")
        self.art = self.sys.generate_draft(principal=self.author, kind=DraftType.TROUBLE_REPORT)

    def test_assign_sets_in_review_and_records_reviewer(self) -> None:
        assigned = self.sys.assign_reviewer(
            tenant_id=T,
            artifact_id=self.art.artifact_id,
            reviewer_id="rev_1",
            reviewer_role="quality_lead",
        )
        self.assertEqual(_status_value(assigned), DraftStatus.IN_REVIEW.value)
        # Reviewer attribution + assigned_at must be present (FR-MFG-010a, contracts §D).
        self.assertEqual(assigned.reviewer_id, "rev_1")
        self.assertEqual(assigned.reviewer_role, "quality_lead")
        self.assertTrue(assigned.assigned_at, "assigned_at must be set on assignment")

    def test_assign_to_group_records_group(self) -> None:
        assigned = self.sys.assign_reviewer(
            tenant_id=T, artifact_id=self.art.artifact_id, reviewer_group="quality_reviewers"
        )
        self.assertEqual(_status_value(assigned), DraftStatus.IN_REVIEW.value)
        self.assertEqual(assigned.reviewer_group, "quality_reviewers")


class TestReviewResponseShape(unittest.TestCase):
    """POST .../review response shape: reviewer-transition fields present on the result."""

    def setUp(self) -> None:
        self.sys = fresh()
        self.author = claims(T, "author")
        self.art = self.sys.generate_draft(principal=self.author, kind=DraftType.QUALITY_REPORT)
        self.sys.assign_reviewer(tenant_id=T, artifact_id=self.art.artifact_id, reviewer_id="rev_2")
        self.reviewer = claims(T, "rev_2", roles=("reviewer",))

    def test_review_response_carries_reviewer_transition_fields(self) -> None:
        reviewed = self.sys.review_draft(
            tenant_id=T,
            artifact_id=self.art.artifact_id,
            reviewer=self.reviewer,
            decision="approved",
            comment="looks correct",
        )
        # contracts §D review res 200 fields: artifact_id, status, reviewer_id, reviewed_at,
        # approval_decision, review_comment.
        self.assertEqual(reviewed.artifact_id, self.art.artifact_id)
        self.assertEqual(_status_value(reviewed), DraftStatus.APPROVED.value)
        self.assertEqual(reviewed.reviewer_id, "rev_2")
        self.assertTrue(reviewed.reviewed_at, "reviewed_at must be set on a review decision")
        self.assertEqual(reviewed.approval_decision, "approved")
        self.assertEqual(reviewed.review_comment, "looks correct")

    def test_reject_decision_shape(self) -> None:
        reviewed = self.sys.review_draft(
            tenant_id=T,
            artifact_id=self.art.artifact_id,
            reviewer=self.reviewer,
            decision="rejected",
            comment="missing approved source",
        )
        self.assertEqual(_status_value(reviewed), DraftStatus.REJECTED.value)
        self.assertEqual(reviewed.approval_decision, "rejected")
        self.assertEqual(reviewed.reviewer_id, "rev_2")


if __name__ == "__main__":
    unittest.main()
