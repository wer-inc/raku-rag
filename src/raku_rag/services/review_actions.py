"""ADR-018 §12.2 / §10.3 — reviewer actions on the extraction/visual review queue.

Closes the HITL loop: ``review_required`` / ``draft_visual`` chunks are quarantined out of retrieval
until a reviewer resolves them. Each action mutates the stored chunk's quality metadata (and, for an
edit, its text + embedding) and writes an audit record with the approver, timestamp, and target chunk
(§10.3). ``approve`` promotes to ``manual_approved`` — high-risk-citation-eligible only when the chunk
still carries a usable citation anchor (§10.3 last bullet). Every backend implements
``store.update_chunk_review`` so the embedding is preserved (an upsert with an empty vector would fail
Postgres' dimension check).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from raku_rag.observability.audit import AuditEvent
from raku_rag.services.ingestion_quality import (
    EXTRACTION_QUALITY_STATUS_KEY,
    HIGH_RISK_CITATION_ELIGIBLE_KEY,
    QUALITY_STATUS_DRAFT_VISUAL,
    QUALITY_STATUS_MANUAL_APPROVED,
    QUALITY_STATUS_REJECTED,
    QUALITY_STATUS_REVIEW_REQUIRED,
    accepted_quality_metadata,
    review_required_quality_metadata,
)

REVIEW_APPROVE = "approve"
REVIEW_EDIT_AND_APPROVE = "edit_and_approve"
REVIEW_REJECT = "reject"
REVIEW_REPROCESS = "reprocess"
REVIEW_MARK_NON_CONTENT = "mark_as_non_content"
REVIEW_ESCALATE = "escalate"

REVIEW_ACTIONS = frozenset(
    {
        REVIEW_APPROVE,
        REVIEW_EDIT_AND_APPROVE,
        REVIEW_REJECT,
        REVIEW_REPROCESS,
        REVIEW_MARK_NON_CONTENT,
        REVIEW_ESCALATE,
    }
)


@dataclass(frozen=True)
class ReviewDecision:
    chunk_id: str
    action: str
    status: str
    reviewed_by: str
    reviewed_at: str
    high_risk_citation_eligible: bool
    retrieval_eligible: bool


def _has_citation_anchor(metadata: dict) -> bool:
    return bool((metadata or {}).get("anchor_type"))


class ReviewActionService:
    def __init__(
        self, store, embedder, *, audit=None, now: Callable[[], str] | None = None
    ) -> None:
        self._store = store
        self._embedder = embedder
        self._audit = audit
        self._now = now or (lambda: datetime.now(timezone.utc).isoformat())

    def apply(
        self,
        *,
        tenant_id: str,
        chunk_id: str,
        action: str,
        actor: str,
        corrected_text: str | None = None,
        reason: str = "",
        correlation_id: str = "",
    ) -> ReviewDecision:
        action = (action or "").strip()
        if action not in REVIEW_ACTIONS:
            raise ValueError(f"unknown review action: {action!r}")
        if not actor:
            raise ValueError("review action requires an actor")
        chunk = self._find(tenant_id, chunk_id)
        if chunk is None:
            raise KeyError(chunk_id)

        reviewed_at = self._now()
        review_fields: dict[str, object] = {
            "reviewed_by": actor,
            "reviewed_at": reviewed_at,
            "review_action": action,
        }
        if reason:
            review_fields["review_reason"] = reason

        text: str | None = None
        vector = None
        tombstone: bool | None = None

        if action in (REVIEW_APPROVE, REVIEW_EDIT_AND_APPROVE):
            # §10.3: a VLM/visual draft may only become high-risk-eligible when it still carries a
            # crop/bbox citation anchor; a text/table review item already has a document+offset citation.
            was_visual = (
                chunk.metadata.get(EXTRACTION_QUALITY_STATUS_KEY) == QUALITY_STATUS_DRAFT_VISUAL
            )
            high_risk_eligible = _has_citation_anchor(chunk.metadata) if was_visual else True
            quality = accepted_quality_metadata(
                status=QUALITY_STATUS_MANUAL_APPROVED,
                high_risk_citation_eligible=high_risk_eligible,
            )
            status = QUALITY_STATUS_MANUAL_APPROVED
            if action == REVIEW_EDIT_AND_APPROVE:
                if not (corrected_text or "").strip():
                    raise ValueError("edit_and_approve requires corrected_text")
                text = corrected_text
                vector = self._embedder.embed([corrected_text])[0]
                review_fields["original_text"] = chunk.text
        elif action == REVIEW_REJECT:
            quality = review_required_quality_metadata(
                status=QUALITY_STATUS_REJECTED, reasons=(reason or "reviewer_rejected",)
            )
            status = QUALITY_STATUS_REJECTED
        elif action == REVIEW_MARK_NON_CONTENT:
            quality = review_required_quality_metadata(
                status=QUALITY_STATUS_REJECTED, reasons=("non_content",)
            )
            status = QUALITY_STATUS_REJECTED
            tombstone = True
        elif action == REVIEW_REPROCESS:
            quality = {
                **review_required_quality_metadata(reasons=(reason or "reprocess_requested",)),
                "reprocess_requested": True,
            }
            status = QUALITY_STATUS_REVIEW_REQUIRED
        else:  # REVIEW_ESCALATE
            quality = {
                **review_required_quality_metadata(reasons=("escalated",)),
                "review_escalated": True,
                "escalated_to": reason,
            }
            status = QUALITY_STATUS_REVIEW_REQUIRED

        metadata = {**quality, **review_fields}
        ok = self._store.update_chunk_review(
            tenant_id, chunk_id, metadata=metadata, text=text, vector=vector, tombstone=tombstone
        )
        if not ok:
            raise KeyError(chunk_id)

        high_risk = bool(metadata.get(HIGH_RISK_CITATION_ELIGIBLE_KEY))
        retrieval_eligible = status == QUALITY_STATUS_MANUAL_APPROVED
        self._audit_record(tenant_id, chunk, action, status, actor, reason, correlation_id)
        return ReviewDecision(
            chunk_id=chunk_id,
            action=action,
            status=status,
            reviewed_by=actor,
            reviewed_at=reviewed_at,
            high_risk_citation_eligible=high_risk,
            retrieval_eligible=retrieval_eligible,
        )

    def _find(self, tenant_id: str, chunk_id: str):
        lister = getattr(self._store, "list_extraction_review_chunks", None)
        if callable(lister):
            for ch in lister(tenant_id):
                if ch.chunk_id == chunk_id and ch.tenant_id == tenant_id:
                    return ch
        iter_items = getattr(self._store, "iter_items", None)
        if callable(iter_items):
            for entry in iter_items():
                ch = entry[0] if isinstance(entry, tuple) else entry
                if ch.chunk_id == chunk_id and getattr(ch, "tenant_id", None) == tenant_id:
                    return ch
        return None

    def _audit_record(
        self, tenant_id, chunk, action, status, actor, reason, correlation_id
    ) -> None:
        if self._audit is None:
            return
        self._audit.record(
            AuditEvent(
                tenant_id=tenant_id,
                correlation_id=correlation_id or f"review:{chunk.chunk_id}",
                action=f"extraction_review.{action}",
                decision=status,
                actor_id=actor,
                resource_type="chunk",
                resource_id=chunk.chunk_id,
                document_ids=(chunk.document_id,),
                chunk_ids=(chunk.chunk_id,),
                reason=reason,
            )
        )
