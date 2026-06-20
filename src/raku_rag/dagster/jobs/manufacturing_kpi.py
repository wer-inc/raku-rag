"""Dagster-compatible manufacturing KPI materialization job descriptors."""

from __future__ import annotations

from dataclasses import dataclass

from raku_rag.dagster.assets.ingestion import DagsterIngestionContext
from raku_rag.dagster.assets.manufacturing import (
    InMemoryManufacturingKpiMaterializationStore,
    ManufacturingDashboardMetricsSnapshot,
    manufacturing_dashboard_metrics,
)


@dataclass(frozen=True)
class ManufacturingKpiJobDefinition:
    name: str = "manufacturing_dashboard_metrics"
    asset_key: str = "manufacturing_dashboard_metrics"
    cron_schedule: str = "0 17 * * *"
    request_path_allowed: bool = False
    manual_refresh_supported: bool = True

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "asset_key": self.asset_key,
            "cron_schedule": self.cron_schedule,
            "request_path_allowed": self.request_path_allowed,
            "manual_refresh_supported": self.manual_refresh_supported,
        }


MANUFACTURING_KPI_JOB = ManufacturingKpiJobDefinition()


def daily_manufacturing_dashboard_metrics_schedule() -> dict:
    return MANUFACTURING_KPI_JOB.to_dict()


def manual_refresh_manufacturing_dashboard_metrics(
    context: DagsterIngestionContext,
    *,
    audit,
    principal,
    iter_meta,
    telemetry=None,
    store: InMemoryManufacturingKpiMaterializationStore | None = None,
    source_ingestion_run_id: str = "",
) -> ManufacturingDashboardMetricsSnapshot:
    return manufacturing_dashboard_metrics(
        context,
        audit=audit,
        principal=principal,
        iter_meta=iter_meta,
        telemetry=telemetry,
        store=store,
        source_ingestion_run_id=source_ingestion_run_id,
    )


__all__ = [
    "MANUFACTURING_KPI_JOB",
    "ManufacturingKpiJobDefinition",
    "daily_manufacturing_dashboard_metrics_schedule",
    "manual_refresh_manufacturing_dashboard_metrics",
]
