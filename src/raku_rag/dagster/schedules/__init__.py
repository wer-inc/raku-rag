"""Dagster-compatible schedule descriptors."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DagsterScheduleSpec:
    name: str
    cron: str
    partition_granularity: str = "tenant/collection/source/sync_run"
    request_path_allowed: bool = False


INGESTION_SCHEDULES: tuple[DagsterScheduleSpec, ...] = (
    DagsterScheduleSpec("scheduled_source_sync", "*/15 * * * *"),
)
