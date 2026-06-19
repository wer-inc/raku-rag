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

from raku_rag.manufacturing.domain.audit import AuditLogEntry, InMemoryAuditLogWriter
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
) -> None:
    """Record one answer-path safety decision. Counter (FR-MFG-021/030 telemetry source)."""
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
        decision=status,
        reason=(",".join(classification.reason_codes) if classification.reason_codes else None),
        high_risk_classification_result=classification.is_high_risk,
        safety_block_reason=reason,
        approval_status_at_use=decision.approval_status_at_use,
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
    writer.record(entry)
