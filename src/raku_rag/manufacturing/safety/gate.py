"""T017 — ManufacturingSafetyGate (FR-MFG-005/006/007/030; contracts/mfg-interfaces.md §4).

A SINGLE overlay stage that runs AFTER the 001 ``GroundednessGate`` — NOT a new gate / security
mechanism. It takes the high-risk classification, the candidate citations the 001 answer path would
cite, and their manufacturing/approval metadata, and decides the safe-side outcome:

- HIGH-RISK and NO approved+effective-date-valid citation among the candidates
    => blocked, ``safety_block_reason=APPROVED_CITATION_MISSING`` (the answer becomes
       ``insufficient_evidence`` and MUST NOT assert; FR-MFG-005, SC-MFG-006).
- An OBSOLETE document among the candidates => ``obsolete_warning=True`` and it is never primary
  evidence (FR-MFG-006, SC-MFG-011). If the ONLY thing that could back an assertion is obsolete/draft,
  the answer cannot be ``ok`` (the approved-evidence-presence check below blocks it).
- A DRAFT document is not formal evidence — never an approved citation.
- Hazardous physical work => ``requires_onsite_confirmation=True`` (FR-MFG-007).
- ``safety_block_reason`` is normalized to ONE code in priority order
  ``approved_citation_missing -> insufficient_evidence -> other_block`` (FR-MFG-030).
- ``approval_status_at_use`` records the status of the evidence actually relied upon.

stdlib only; frozen value objects from ``manufacturing.domain.safety``.
"""

from __future__ import annotations

from datetime import date
from typing import Mapping, Sequence

from raku_rag.domain.models import Citation, PROMOTABLE_EXTRACTION_SOURCES
from raku_rag.manufacturing.domain.metadata import ApprovalStatus, ManufacturingDocumentMetadata
from raku_rag.manufacturing.domain.safety import (
    HighRiskClassification,
    SafetyBlockReason,
    SafetyDecision,
)

VISUAL_DERIVED_CITATION_KINDS = frozenset(
    {"visual", "table_row", "form_field", "chart_series", "figure_caption"}
)


def is_promotable_evidence(metadata: Mapping[str, object] | None) -> bool:
    """True when non-text evidence carries transcription provenance eligible for primary use."""

    if not metadata:
        return False
    source = str(
        metadata.get("primary_evidence_source") or metadata.get("extraction_source") or ""
    )
    return source in PROMOTABLE_EXTRACTION_SOURCES


def is_effective(effective_date: str | None, *, today: date | None = None) -> bool:
    """An effective_date is VALID iff it is set and not in the future (not-yet-effective => invalid).

    Missing date => invalid (no validity window asserted). A malformed date fails safe to invalid.
    """
    if not effective_date:
        return False
    today = today or date.today()
    try:
        eff = date.fromisoformat(effective_date[:10])
    except (ValueError, TypeError):
        return False
    return eff <= today


def is_approved_effective(
    meta: ManufacturingDocumentMetadata | None, *, today: date | None = None
) -> bool:
    """A citation is a VALID approved citation iff approved AND its effective_date is valid."""
    if meta is None:
        return False
    if meta.approval_status != ApprovalStatus.APPROVED:
        return False
    return is_effective(meta.effective_date, today=today)


def citation_is_approved_effective(
    citation: Citation,
    meta: ManufacturingDocumentMetadata | None,
    *,
    today: date | None = None,
    visual_evidence_promotion: bool = False,
) -> bool:
    """True when a citation may satisfy the high-risk approved/effective requirement.

    Text citations keep the existing approved/effective rule. Non-text citations must carry
    promotable transcription provenance, and pixel-derived citations also need the visual verifier
    path when promotion is explicitly enabled.
    """

    if not is_approved_effective(meta, today=today):
        return False
    if citation.kind == "text":
        return True
    if not is_promotable_evidence(getattr(citation, "metadata", None)):
        return False
    pixel_derived = bool(
        getattr(citation, "pixel_derived", False)
        or citation.kind in VISUAL_DERIVED_CITATION_KINDS
    )
    if pixel_derived:
        return bool(visual_evidence_promotion and citation.visual_evidence_verified)
    return True


class ManufacturingSafetyGate:
    """Concrete SafetyGate overlay (structurally satisfies interfaces.SafetyGate).

    ``evaluate`` matches the ABC signature; the answer wiring (api/answer_ext.py) consumes the
    returned ``SafetyDecision`` to shape the final ``ManufacturingAnswer``.
    """

    def __init__(
        self,
        *,
        today: date | None = None,
        visual_evidence_promotion: bool = False,
    ) -> None:
        # Injectable clock for deterministic tests; defaults to the real today at evaluate-time.
        self._today = today
        self._visual_evidence_promotion = visual_evidence_promotion

    def evaluate(
        self,
        classification: HighRiskClassification,
        candidate_citations: Sequence[Citation],
        candidate_metadata: Sequence[ManufacturingDocumentMetadata],
    ) -> SafetyDecision:
        today = self._today  # None => is_effective uses date.today() per call

        by_doc = {m.document_id: m for m in candidate_metadata if m is not None}

        # Approval/state survey over the candidate evidence (what 001 would otherwise cite).
        has_approved_effective = any(
            citation_is_approved_effective(
                c,
                by_doc.get(c.document_id),
                today=today,
                visual_evidence_promotion=self._visual_evidence_promotion,
            )
            for c in candidate_citations
        )
        has_obsolete = any(
            (by_doc.get(c.document_id) is not None)
            and by_doc[c.document_id].approval_status == ApprovalStatus.OBSOLETE
            for c in candidate_citations
        )

        # (FR-MFG-006) For a NON-high-risk answer the approved-citation requirement does NOT apply
        # (that is a high-risk rule, FR-MFG-005); only draft/obsolete are excluded as PRIMARY
        # evidence. Evidence that is approved, pending_review, or carries no manufacturing metadata
        # is a usable primary basis.
        def _usable_primary(meta: ManufacturingDocumentMetadata | None) -> bool:
            if meta is None:
                return True
            return meta.approval_status not in (ApprovalStatus.DRAFT, ApprovalStatus.OBSOLETE)

        has_usable_primary = any(
            _usable_primary(by_doc.get(c.document_id)) for c in candidate_citations
        )

        # The approval status of the evidence actually relied upon (the approved+effective one if any).
        approval_status_at_use: str | None = None
        for c in candidate_citations:
            m = by_doc.get(c.document_id)
            if citation_is_approved_effective(
                c,
                m,
                today=today,
                visual_evidence_promotion=self._visual_evidence_promotion,
            ):
                approval_status_at_use = ApprovalStatus.APPROVED.value
                break

        # (FR-MFG-005/007) HIGH-RISK requires an approved+effective citation, else MUST NOT assert.
        if classification.is_high_risk and not has_approved_effective:
            return SafetyDecision(
                blocked=True,
                safety_block_reason=SafetyBlockReason.APPROVED_CITATION_MISSING,
                obsolete_warning=has_obsolete,
                requires_onsite_confirmation=True,
                approval_status_at_use=None,
            )

        # (FR-MFG-005/006) The approved+effective requirement is a HIGH-RISK rule (enforced above).
        # For a NON-high-risk answer, only draft/obsolete are excluded as PRIMARY evidence
        # (FR-MFG-006, SC-MFG-011); approved / pending_review / unclassified evidence may back the
        # answer. Block only when the sole candidate evidence is draft/obsolete. Obsolete raises the
        # mandatory warning even when it is not the primary basis.
        if not classification.is_high_risk and not has_usable_primary:
            return SafetyDecision(
                blocked=True,
                safety_block_reason=SafetyBlockReason.INSUFFICIENT_EVIDENCE,
                obsolete_warning=has_obsolete,
                requires_onsite_confirmation=False,
                approval_status_at_use=None,
            )

        # Approved + effective evidence present => allowed. On-site confirmation when high-risk.
        return SafetyDecision(
            blocked=False,
            safety_block_reason=None,
            obsolete_warning=has_obsolete,
            requires_onsite_confirmation=classification.is_high_risk,
            approval_status_at_use=approval_status_at_use,
        )


# --- normalization (FR-MFG-030): 1 block = 1 primary cause -----------------------------------------
_BLOCK_PRIORITY: tuple[SafetyBlockReason, ...] = (
    SafetyBlockReason.APPROVED_CITATION_MISSING,
    SafetyBlockReason.INSUFFICIENT_EVIDENCE,
    SafetyBlockReason.OTHER_BLOCK,
)


def normalize_block_reason(*reasons: SafetyBlockReason | None) -> SafetyBlockReason | None:
    """Collapse several applicable block reasons to the single highest-priority one (FR-MFG-030)."""
    present = {r for r in reasons if r is not None}
    for candidate in _BLOCK_PRIORITY:
        if candidate in present:
            return candidate
    return None
