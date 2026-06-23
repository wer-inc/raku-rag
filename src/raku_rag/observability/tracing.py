"""T015/T034/T062 - minimal in-memory tracing boundary."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterator

from raku_rag.observability.exporters import TelemetryEvent, TelemetryExporter, safe_export


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class TraceSpan:
    name: str
    correlation_id: str
    tenant_id: str = ""
    attributes: dict = field(default_factory=dict)
    started_at: str = field(default_factory=_now)
    ended_at: str = ""
    status: str = "running"

    def finish(self, status: str = "ok", **attributes) -> None:
        self.status = status
        self.ended_at = _now()
        self.attributes.update(attributes)


@dataclass(frozen=True)
class TraceCompletenessReport:
    correlation_id: str
    required_spans: tuple[str, ...]
    present_spans: tuple[str, ...]
    missing_spans: tuple[str, ...]

    @property
    def complete(self) -> bool:
        return not self.missing_spans


@dataclass
class InMemoryTracer:
    _spans: list[TraceSpan] = field(default_factory=list)
    exporter: TelemetryExporter | None = field(default=None, repr=False)

    @contextmanager
    def span(
        self, name: str, *, correlation_id: str = "", tenant_id: str = "", **attributes
    ) -> Iterator[TraceSpan]:
        span = TraceSpan(
            name=name,
            correlation_id=correlation_id,
            tenant_id=tenant_id,
            attributes=dict(attributes),
        )
        self._spans.append(span)
        try:
            yield span
            if span.status == "running":
                span.finish("ok")
            self._export_span(span)
        except Exception:
            span.finish("error")
            self._export_span(span)
            raise

    def spans(self, *, correlation_id: str = "") -> tuple[TraceSpan, ...]:
        if correlation_id:
            return tuple(span for span in self._spans if span.correlation_id == correlation_id)
        return tuple(self._spans)

    def verify_completeness(
        self,
        correlation_id: str,
        required_spans: tuple[str, ...],
    ) -> TraceCompletenessReport:
        present = tuple(span.name for span in self.spans(correlation_id=correlation_id))
        missing = tuple(name for name in required_spans if name not in present)
        return TraceCompletenessReport(
            correlation_id=correlation_id,
            required_spans=required_spans,
            present_spans=present,
            missing_spans=missing,
        )

    def _export_span(self, span: TraceSpan) -> None:
        safe_export(
            self.exporter,
            TelemetryEvent(
                kind="span",
                name=span.name,
                payload={
                    "correlation_id": span.correlation_id,
                    "tenant_id": span.tenant_id,
                    "status": span.status,
                    "started_at": span.started_at,
                    "ended_at": span.ended_at,
                    "attributes": dict(span.attributes),
                },
            ),
        )
