"""ADR-018 §18.3 — ingestion cost model (config-driven, honest by default).

Per-provider cost is deployment- and contract-specific, so it is a CONFIG surface: a JSON map in
``RAKU_INGEST_COST_MODEL`` (provider name -> cost per call, e.g. per OCR/VLM page). The default is an
empty map, so cost aggregates report 0 (unknown) rather than a made-up number. Latency, by contrast, is
measured directly (RouteTraceStep.latency_ms) and needs no config.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping

COST_MODEL_ENV = "RAKU_INGEST_COST_MODEL"


def provider_cost_model() -> dict[str, float]:
    """Per-provider cost-per-call from ``RAKU_INGEST_COST_MODEL`` (JSON). Empty (all unknown) by default."""

    raw = os.environ.get(COST_MODEL_ENV)
    if not raw or not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    if not isinstance(parsed, Mapping):
        return {}
    model: dict[str, float] = {}
    for name, value in parsed.items():
        try:
            model[str(name)] = float(value)
        except (TypeError, ValueError):
            continue
    return model
