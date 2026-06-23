"""Telemetry export seams for metrics and spans.

The in-process metrics/tracer remain the fast test oracle. When production wiring opts in, the same
events can also be exported as sanitized structured records that ECS can ship to CloudWatch Logs or an
OpenTelemetry collector sidecar.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from typing import Protocol

from raku_rag.observability.logging import log
from raku_rag.observability.redaction import Redactor

_REDACTOR = Redactor()
_IDENTITY_LABELS = {"tenant_id", "user_id", "tenant", "user"}


@dataclass(frozen=True)
class TelemetryEvent:
    kind: str
    name: str
    payload: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"kind": self.kind, "name": self.name, "payload": dict(self.payload)}


class TelemetryExporter(Protocol):
    def export(self, event: TelemetryEvent) -> None: ...


@dataclass
class InMemoryTelemetryExporter:
    _events: list[TelemetryEvent] = field(default_factory=list)

    def export(self, event: TelemetryEvent) -> None:
        self._events.append(TelemetryEvent(event.kind, event.name, sanitize_payload(event.payload)))

    def events(self, *, kind: str = "", name: str = "") -> tuple[TelemetryEvent, ...]:
        return tuple(
            event
            for event in self._events
            if (not kind or event.kind == kind) and (not name or event.name == name)
        )


class StructuredLogTelemetryExporter:
    """Export telemetry as one sanitized JSON log record per event."""

    def export(self, event: TelemetryEvent) -> None:
        log(f"telemetry.{event.kind}", name=event.name, payload=sanitize_payload(event.payload))


def exporter_from_settings(settings) -> TelemetryExporter | None:
    return (
        StructuredLogTelemetryExporter()
        if getattr(settings, "telemetry_export_enabled", False)
        else None
    )


def safe_export(exporter: TelemetryExporter | None, event: TelemetryEvent) -> None:
    if exporter is None:
        return
    try:
        exporter.export(TelemetryEvent(event.kind, event.name, sanitize_payload(event.payload)))
    except Exception:
        # Telemetry must never take down retrieval/generation.
        return


def sanitize_payload(value):
    if isinstance(value, str):
        return _REDACTOR.redact(value)
    if isinstance(value, dict):
        return {
            str(k): sanitize_payload(_sanitize_identity_label(str(k), v)) for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [sanitize_payload(item) for item in value]
    return value


def sanitize_labels(labels: dict[str, str] | None) -> dict[str, str]:
    sanitized: dict[str, str] = {}
    for key, value in (labels or {}).items():
        sanitized[key] = str(_sanitize_identity_label(key, value))
    return sanitized


def _sanitize_identity_label(key: str, value):
    if key in _IDENTITY_LABELS:
        return _identity_hash(str(value))
    return value


def _identity_hash(value: str) -> str:
    if not value:
        return ""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
