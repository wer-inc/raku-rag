"""T034 - reference-only audit events for the base RAG answer/retrieval path."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Mapping, Protocol

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


class AuditSink(Protocol):
    def record(self, event: AuditEvent) -> AuditEvent: ...

    def events(
        self, tenant_id: str | None = None, *, correlation_id: str = ""
    ) -> tuple[AuditEvent, ...]: ...


def sanitize_audit_event(event: AuditEvent, redactor: Redactor | None = None) -> AuditEvent:
    """Return the reference-only audit event with free-text fields redacted."""
    redactor = redactor or _redactor
    return AuditEvent(
        tenant_id=event.tenant_id,
        correlation_id=event.correlation_id,
        action=event.action,
        decision=redactor.redact(event.decision),
        actor_id=event.actor_id,
        resource_type=event.resource_type,
        resource_id=event.resource_id,
        document_ids=event.document_ids,
        chunk_ids=event.chunk_ids,
        reason=redactor.redact(event.reason),
        created_at=event.created_at,
        metadata=_redact_metadata(event.metadata, redactor),
    )


def _redact_metadata(value: object, redactor: Redactor) -> object:
    if isinstance(value, str):
        return redactor.redact(value)
    if isinstance(value, Mapping):
        return {str(key): _redact_metadata(child, redactor) for key, child in value.items()}
    if isinstance(value, list):
        return [_redact_metadata(child, redactor) for child in value]
    if isinstance(value, tuple):
        return tuple(_redact_metadata(child, redactor) for child in value)
    return value


@dataclass
class InMemoryAuditSink:
    _events: list[AuditEvent] = field(default_factory=list)

    def record(self, event: AuditEvent) -> AuditEvent:
        redacted = sanitize_audit_event(event, _redactor)
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
