"""Dagster-compatible sensor descriptors."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DagsterSensorSpec:
    name: str
    description: str
    partition_granularity: str = "tenant/collection/source/sync_run"
    request_path_allowed: bool = False


INGESTION_SENSORS: tuple[DagsterSensorSpec, ...] = (
    DagsterSensorSpec("queued_source_sync_sensor", "Observes queued source sync runs"),
    DagsterSensorSpec(
        "failed_document_retry_sensor", "Observes failed document states for retry orchestration"
    ),
)
