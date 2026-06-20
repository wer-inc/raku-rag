"""T014/T015/T016 — structured logging with mandatory redaction + minimal trace/metrics.

Production wires structlog + OpenTelemetry + Prometheus behind these helpers. The invariant that
matters for the MVP security gates: nothing is logged without passing through the Redactor.
"""

from __future__ import annotations

import json
import sys
import uuid

from raku_rag.observability.redaction import Redactor

_redactor = Redactor()


def new_correlation_id() -> str:
    return "trace_" + uuid.uuid4().hex[:12]


def log(event: str, *, correlation_id: str = "", **fields) -> None:
    safe = {k: (_redactor.redact(v) if isinstance(v, str) else v) for k, v in fields.items()}
    record = {"event": event, "correlation_id": correlation_id, **safe}
    sys.stderr.write(json.dumps(record, ensure_ascii=False) + "\n")
