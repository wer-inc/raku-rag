"""T042 — ReviewWorkflow: the lightweight draft review state machine (US4; FR-MFG-010a, Hard Rule 1).

State machine (data-model §F):
    draft -> in_review -> approved | rejected | archived ;  draft -> archived

CENTRAL SAFETY INVARIANT (SC-MFG-007): ``approved`` is reachable ONLY through an explicit human
reviewer action. ``assign_reviewer`` records who must review (single reviewer_id or reviewer_group);
``review`` records the reviewer's decision. An approve decision REQUIRES an attributable reviewer_id
— a review call carrying no reviewer is REJECTED (raises ``PermissionError``) and the artifact stays
``draft``. ``created_by=ai`` is never rewritten by an approval; the approval is attributed to the
reviewer instead. Single reviewer / reviewer group only — no multi-stage approval, no e-signature.

This workflow mutates the STORED artifact in the draft store (the system of record). It never trusts
a status the caller set directly on a detached dataclass copy; the only transitions it honors are the
ones it performs here, all audited (FR-MFG-021).

stdlib only.
"""

from __future__ import annotations

from datetime import datetime, timezone

from raku_rag.domain.models import IdentityClaims
from raku_rag.manufacturing.domain.draft import DraftArtifact, DraftStatus

# Reviewer decisions that the review endpoint accepts (contracts §D).
_VALID_DECISIONS = ("approved", "rejected", "archived")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ReviewWorkflow:
    """Concrete ReviewWorkflow (structurally satisfies interfaces.ReviewWorkflow).

    Operates on a STORED DraftArtifact passed by the orchestrating ``DraftService`` (the system of
    record), returning the same mutated stored object so the store reflects every transition.
    """

    def assign(
        self,
        artifact: DraftArtifact,
        *,
        reviewer_id: str | None = None,
        reviewer_group: str | None = None,
        reviewer_role: str | None = None,
    ) -> DraftArtifact:
        """draft -> in_review. Records who must review (single reviewer or group) + assigned_at."""
        if reviewer_id is None and reviewer_group is None:
            raise ValueError("assign requires a reviewer_id or reviewer_group")
        artifact.status = DraftStatus.IN_REVIEW
        artifact.reviewer_id = reviewer_id
        artifact.reviewer_group = reviewer_group
        artifact.reviewer_role = reviewer_role
        artifact.assigned_at = _now()
        return artifact

    def decide(
        self,
        artifact: DraftArtifact,
        *,
        reviewer: IdentityClaims | None,
        decision: str,
        comment: str | None = None,
    ) -> DraftArtifact:
        """Record a reviewer decision. ``approved`` REQUIRES an attributable human reviewer.

        Hard Rule 1 / SC-MFG-007: an approve attempt with no reviewer (``reviewer is None``) is
        rejected by raising ``PermissionError``; the artifact is NOT mutated and stays ``draft``.
        A valid reviewer approval sets status=approved + reviewer attribution; created_by stays ai.
        """
        if decision not in _VALID_DECISIONS:
            raise ValueError(f"invalid review decision: {decision!r}")

        # The ONLY path to approved is an explicit, attributable human reviewer action.
        if decision == "approved":
            reviewer_id = getattr(reviewer, "user_id", None) if reviewer is not None else None
            if reviewer is None or not reviewer_id:
                # AI self-approve / unattributable approval — reject; artifact unchanged.
                raise PermissionError(
                    "approved requires an explicit reviewer (AI cannot self-approve, SC-MFG-007)"
                )
            artifact.status = DraftStatus.APPROVED
            artifact.reviewer_id = reviewer_id
            artifact.reviewer_role = self._reviewer_role(reviewer)
        elif decision == "rejected":
            artifact.status = DraftStatus.REJECTED
            artifact.reviewer_id = self._reviewer_id(reviewer, artifact)
        else:  # archived
            artifact.status = DraftStatus.ARCHIVED
            artifact.reviewer_id = self._reviewer_id(reviewer, artifact)

        artifact.reviewed_at = _now()
        artifact.approval_decision = decision
        artifact.review_status = decision
        artifact.review_comment = comment
        # created_by is provenance (ai) and is NOT rewritten — the approval is the reviewer's.
        return artifact

    @staticmethod
    def _reviewer_id(reviewer: IdentityClaims | None, artifact: DraftArtifact) -> str | None:
        if reviewer is not None and getattr(reviewer, "user_id", None):
            return reviewer.user_id
        # Fall back to the assigned reviewer recorded at assignment time.
        return artifact.reviewer_id

    @staticmethod
    def _reviewer_role(reviewer: IdentityClaims) -> str | None:
        roles = getattr(reviewer, "roles", ()) or ()
        return roles[0] if roles else None
