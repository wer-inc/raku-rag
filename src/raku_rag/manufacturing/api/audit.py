"""T020 — record the SafetyGate / high-risk decision into the Phase-2 audit log (FR-MFG-021).

Builds a reference-IDs-only ``AuditLogEntry`` from an answer-path decision and hands it to the reused
``InMemoryAuditLogWriter`` (which redacts free text and enforces 001 tenancy). Captured per
spec §safety/audit + data-model §H:
  - ``high_risk_classification_result`` (the high-risk decision),
  - ``safety_block_reason`` (approved_citation_missing / insufficient_evidence / other_block),
  - ``approval_status_at_use`` (status of the evidence relied upon),
  - obsolete-warning flag (in ``client_metadata`` — non-PII boolean),
  - evidence references by ID only (``document_ids_used`` = candidate doc ids).

No PII / body text is recorded; the writer redacts as defence-in-depth.
"""

from __future__ import annotations

from datetime import datetime, timezone

from raku_rag.domain.models import IdentityClaims
from raku_rag.manufacturing.domain.audit import (
    AuditLogEntry,
    InMemoryAuditLogWriter,
    stamp_org_context,
)
from raku_rag.manufacturing.domain.safety import (
    HighRiskClassification,
    SafetyBlockReason,
    SafetyDecision,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def record_answer_decision(
    writer: InMemoryAuditLogWriter,
    *,
    tenant_id: str,
    actor_id: str,
    correlation_id: str,
    status: str,
    classification: HighRiskClassification,
    decision: SafetyDecision,
    safety_block_reason: str | None,
    candidate_document_ids: tuple[str, ...],
    citation_ids: tuple[str, ...] = (),
    principal: IdentityClaims | None = None,
    factory_id: str | None = None,
    collection_id: str | None = None,
) -> None:
    """Record one answer-path safety decision. Counter (FR-MFG-021/030 telemetry source).

    ``citation_ids`` are the reference IDs of the citations actually relied upon for an asserted
    answer (citation-access auditing, FR-MFG-021); empty for a blocked / non-asserting answer.

    When ``principal`` is supplied the actor org-context (factory == the supplied ``factory_id``
    territory; department == the actor's primary 001 ACL group) is SNAPSHOTTED onto the immutable
    entry (T056 ``stamp_org_context``) so US5 safety-telemetry can group by factory/department
    without re-resolving a mutable identity. Default-safe: omitting ``principal`` leaves the
    org-context unset (prior behaviour unchanged).
    """
    reason: SafetyBlockReason | None = None
    if safety_block_reason is not None:
        reason = SafetyBlockReason(safety_block_reason)

    entry = AuditLogEntry(
        tenant_id=tenant_id,
        log_id=f"answer:{correlation_id or _now()}",
        timestamp=_now(),
        request_id=correlation_id or None,
        actor_id=actor_id,
        action="answer.safety_evaluated",
        resource_type="answer",
        resource_id=correlation_id or None,
        collection_id=collection_id,  # FR-MFG-030 collection axis (reference ID; None = cross-collection)
        decision=status,
        reason=(",".join(classification.reason_codes) if classification.reason_codes else None),
        high_risk_classification_result=classification.is_high_risk,
        safety_block_reason=reason,
        approval_status_at_use=decision.approval_status_at_use,
        citation_ids=tuple(citation_ids),
        document_ids_used=tuple(candidate_document_ids),
        client_metadata={
            "obsolete_warning": decision.obsolete_warning,
            "requires_onsite_confirmation": decision.requires_onsite_confirmation,
            "classification_source": (
                classification.classification_source.value
                if classification.classification_source is not None
                else None
            ),
        },
    )
    # T056 — snapshot the actor org-context (factory/department) onto the immutable entry so US5
    # telemetry can group by factory/department. No-op when no principal is supplied.
    if principal is not None:
        entry = stamp_org_context(entry, principal, factory_id=factory_id)
    writer.record(entry)


# --- GAP-F4: low-rating / feedback funnel (FR-MFG-021/012/028) ---------------------------------
# Rating scale = 1-5 (mirrors the 001 FeedbackRequest DTO); low = rating <= LOW_RATING_THRESHOLD.
# Feedback is ALWAYS audited, carrying a low_rating flag + the numeric score (non-PII; numbers/bools
# are not redacted); the low-rating views COUNT the low ones. The free-text comment is NEVER stored
# in the audit (PII-risk, SC-MFG-010 = 0) — it is not even a parameter of this emitter.
LOW_RATING_THRESHOLD = 2
FEEDBACK_ACTION = "feedback.low_rating"
FEEDBACK_LOW_DECISION = "low_rating"


def record_answer_feedback(
    writer: InMemoryAuditLogWriter,
    *,
    tenant_id: str,
    actor_id: str,
    rating: int,
    answer_correlation_id: str = "",
    document_ids: tuple[str, ...] = (),
    collection_id: str | None = None,
) -> bool:
    """Audit one answer-feedback event (reference IDs only). Returns True iff it is a LOW rating.

    ``rating`` is 1-5 (001 FeedbackRequest convention); ``rating <= LOW_RATING_THRESHOLD`` is low.
    The feedback is ALWAYS recorded; the low-rating flag/score lets the audit-derived dashboard/KPI
    COUNT the low ones (single source of truth, like the safety telemetry). The comment body is
    intentionally NOT a parameter — no free text reaches the audit (SC-MFG-010 = PII 0).
    """
    is_low = int(rating) <= LOW_RATING_THRESHOLD
    ts = _now()
    entry = AuditLogEntry(
        tenant_id=tenant_id,
        log_id=f"feedback:{answer_correlation_id or ts}:{ts}",
        timestamp=ts,
        request_id=answer_correlation_id or None,
        actor_id=actor_id,
        action=FEEDBACK_ACTION,
        resource_type="answer",
        resource_id=answer_correlation_id or None,  # reference ID only
        collection_id=collection_id,
        decision=(FEEDBACK_LOW_DECISION if is_low else "rating"),  # reference label, not body text
        reason="feedback",  # reference label (a category), never the comment
        document_ids_used=tuple(document_ids),
        client_metadata={"rating": int(rating), "low_rating": is_low},  # numeric/bool: not redacted
    )
    writer.record(entry)
    return is_low
