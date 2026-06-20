"""Provider configuration audit events with redacted before/after snapshots."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Mapping

from raku_rag.observability.redaction import Redactor

_SENSITIVE_KEY = re.compile(
    r"(?:^|_)(?:api_?key|access_?key|secret|token|password|credential|private_?key)(?:$|_)",
    re.IGNORECASE,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class ProviderConfigAuditEvent:
    provider_config_audit_event_id: str
    tenant_id: str
    event_type: str
    actor: str
    redacted_before: Mapping[str, object]
    redacted_after: Mapping[str, object]
    collection_id: str | None = None
    reason: str = ""
    approval_ref: str = ""
    created_at: str = field(default_factory=_now)
    correlation_id: str = ""

    def to_dict(self) -> dict:
        payload = {
            "provider_config_audit_event_id": self.provider_config_audit_event_id,
            "tenant_id": self.tenant_id,
            "collection_id": self.collection_id,
            "event_type": self.event_type,
            "actor": self.actor,
            "redacted_before": dict(self.redacted_before),
            "redacted_after": dict(self.redacted_after),
            "reason": self.reason,
            "created_at": self.created_at,
            "correlation_id": self.correlation_id,
        }
        if self.approval_ref:
            payload["approval_ref"] = self.approval_ref
        return payload


class ProviderConfigAuditRepository:
    """Tenant-scoped in-memory audit repository used by the app-facing control plane."""

    def __init__(self, redactor: Redactor | None = None) -> None:
        self._redactor = redactor or Redactor()
        self._events: dict[str, list[ProviderConfigAuditEvent]] = {}
        self._counter = 0

    def record_change(
        self,
        *,
        tenant_id: str,
        event_type: str,
        actor: str,
        before: Mapping[str, object] | None,
        after: Mapping[str, object] | None,
        reason: str = "",
        collection_id: str | None = None,
        approval_ref: str = "",
        correlation_id: str = "",
    ) -> ProviderConfigAuditEvent:
        self._counter += 1
        redacted_before = self.redact_snapshot(before or {})
        redacted_after = self.redact_snapshot(after or {})
        digest = hashlib.sha256(
            json.dumps(
                [
                    tenant_id,
                    event_type,
                    correlation_id,
                    self._counter,
                    redacted_before,
                    redacted_after,
                ],
                sort_keys=True,
                default=str,
            ).encode()
        ).hexdigest()[:12]
        event = ProviderConfigAuditEvent(
            provider_config_audit_event_id=f"aud_{digest}",
            tenant_id=tenant_id,
            collection_id=collection_id,
            event_type=event_type,
            actor=self._redactor.redact(actor),
            redacted_before=redacted_before,
            redacted_after=redacted_after,
            reason=self._redactor.redact(reason),
            approval_ref=approval_ref,
            correlation_id=correlation_id,
        )
        self._events.setdefault(tenant_id, []).append(event)
        return event

    def list_events(
        self,
        tenant_id: str,
        *,
        event_type: str = "",
        correlation_id: str = "",
        collection_id: str = "",
    ) -> tuple[ProviderConfigAuditEvent, ...]:
        events = self._events.get(tenant_id, [])
        if event_type:
            events = [event for event in events if event.event_type == event_type]
        if correlation_id:
            events = [event for event in events if event.correlation_id == correlation_id]
        if collection_id:
            events = [event for event in events if event.collection_id == collection_id]
        return tuple(events)

    def redact_snapshot(self, value: Mapping[str, object]) -> dict[str, object]:
        return self._redact_mapping(value)

    def _redact_mapping(self, value: Mapping[str, object]) -> dict[str, object]:
        return {str(key): self._redact_value(str(key), child) for key, child in value.items()}

    def _redact_value(self, key: str, value: object) -> object:
        if _SENSITIVE_KEY.search(key):
            return "[REDACTED:secret]"
        if isinstance(value, Mapping):
            return self._redact_mapping(value)
        if isinstance(value, list):
            return [self._redact_value(key, child) for child in value]
        if isinstance(value, tuple):
            return [self._redact_value(key, child) for child in value]
        if isinstance(value, str):
            return self._redactor.redact(value)
        return value
