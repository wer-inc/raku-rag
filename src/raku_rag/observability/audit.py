"""T034 - reference-only audit events for the base RAG answer/retrieval path."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from raku_rag.observability.redaction import Redactor

_redactor = Redactor()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class AuditEvent:
    tenant_id: str
    correlation_id: str
    action: str
    decision: str
    actor_id: str = ""
    resource_type: str = ""
    resource_id: str = ""
    document_ids: tuple[str, ...] = ()
    chunk_ids: tuple[str, ...] = ()
    reason: str = ""
    created_at: str = field(default_factory=_now)
    metadata: dict = field(default_factory=dict)


@dataclass
class InMemoryAuditSink:
    _events: list[AuditEvent] = field(default_factory=list)

    def record(self, event: AuditEvent) -> AuditEvent:
        redacted_metadata = {
            key: _redactor.redact(value) if isinstance(value, str) else value
            for key, value in event.metadata.items()
        }
        redacted = AuditEvent(
            tenant_id=event.tenant_id,
            correlation_id=event.correlation_id,
            action=event.action,
            decision=_redactor.redact(event.decision),
            actor_id=event.actor_id,
            resource_type=event.resource_type,
            resource_id=event.resource_id,
            document_ids=event.document_ids,
            chunk_ids=event.chunk_ids,
            reason=_redactor.redact(event.reason),
            created_at=event.created_at,
            metadata=redacted_metadata,
        )
        self._events.append(redacted)
        return redacted

    def events(
        self, tenant_id: str | None = None, *, correlation_id: str = ""
    ) -> tuple[AuditEvent, ...]:
        events = self._events
        if tenant_id is not None:
            events = [event for event in events if event.tenant_id == tenant_id]
        if correlation_id:
            events = [event for event in events if event.correlation_id == correlation_id]
        return tuple(events)
