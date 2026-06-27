"""MVP Completion — knowledge improvement queue derived from the audit log (FR-MFG-012/028).

Single source of truth: the shared ``AuditLogWriter``. No parallel feedback store; reference IDs only.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from raku_rag.domain.models import IdentityClaims
from raku_rag.manufacturing.api import audit as audit_derive
from raku_rag.manufacturing.interfaces import AuditLogWriter


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class ImprovementQueueItem:
    id: str
    kind: str
    answer_id: str | None
    document_ids: tuple[str, ...]
    reason: str | None
    created_at: str
    rating: int | None = None
    safety_block_reason: str | None = None


@dataclass(frozen=True)
class ImprovementQueueView:
    items: tuple[ImprovementQueueItem, ...] = ()
    total: int = 0
    correlation_id: str = ""


class ImprovementQueueService:
    def __init__(self, audit: AuditLogWriter) -> None:
        self._audit = audit

    def list_items(self, principal: IdentityClaims, *, limit: int = 100) -> ImprovementQueueView:
        entries = self._audit.read_all(principal)
        answer_entries = audit_derive.answer_entries(entries)
        items: list[ImprovementQueueItem] = []

        for e in audit_derive.low_rating_feedback_entries(entries):
            items.append(
                ImprovementQueueItem(
                    id=e.log_id,
                    kind="low_rating",
                    answer_id=e.resource_id,
                    document_ids=tuple(e.document_ids_used),
                    reason="low_rating",
                    created_at=e.timestamp,
                    rating=int(e.client_metadata.get("rating") or 0) or None,
                )
            )

        for e in answer_entries:
            if e.decision == "insufficient_evidence" or (
                e.safety_block_reason is not None and e.decision != "ok"
            ):
                kind = (
                    "insufficient_evidence"
                    if e.decision == "insufficient_evidence"
                    else "safety_block"
                )
                items.append(
                    ImprovementQueueItem(
                        id=e.log_id,
                        kind=kind,
                        answer_id=e.resource_id,
                        document_ids=tuple(e.document_ids_used),
                        reason=e.reason,
                        created_at=e.timestamp,
                        safety_block_reason=(
                            e.safety_block_reason.value
                            if e.safety_block_reason is not None
                            else None
                        ),
                    )
                )
            elif e.client_metadata.get("obsolete_warning"):
                items.append(
                    ImprovementQueueItem(
                        id=e.log_id,
                        kind="obsolete_only",
                        answer_id=e.resource_id,
                        document_ids=tuple(e.document_ids_used),
                        reason="obsolete_warning",
                        created_at=e.timestamp,
                    )
                )

        items.sort(key=lambda i: i.created_at, reverse=True)
        capped = tuple(items[: max(1, min(limit, 500))])
        return ImprovementQueueView(
            items=capped,
            total=len(items),
            correlation_id=f"improvements:{_now()}",
        )
