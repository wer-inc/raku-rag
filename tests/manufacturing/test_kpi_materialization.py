from __future__ import annotations

import unittest

from raku_rag.dagster.assets.ingestion import DagsterIngestionContext
from raku_rag.dagster.jobs.manufacturing_kpi import (
    daily_manufacturing_dashboard_metrics_schedule,
    manual_refresh_manufacturing_dashboard_metrics,
)
from raku_rag.manufacturing.api.dashboard import DashboardService
from raku_rag.manufacturing.telemetry.safety_metrics import SafetyTelemetry

from tests.manufacturing.helpers import T, claims, fresh, mfg_meta


class ManufacturingKpiMaterializationTest(unittest.TestCase):
    def test_materialized_kpi_snapshot_is_read_by_dashboard_without_dagster_request_call(
        self,
    ) -> None:
        sys = fresh()
        principal = claims(T, "admin", roles=("admin",))
        sys.ingest_manufacturing(
            tenant_id=T,
            collection_id="manuals",
            document_id="doc_a",
            text="Approved press alarm procedure for E-142.",
            metadata=mfg_meta(tenant_id=T, document_id="doc_a"),
        )
        sys.answer(principal, "press alarm procedure", collection_id="manuals")
        context = DagsterIngestionContext(
            tenant_id=T,
            collection_id="manuals",
            source_id="source_a",
            sync_run_id="sync_1",
            dagster_run_id="dagster_kpi_1",
        )

        snapshot = manual_refresh_manufacturing_dashboard_metrics(
            context,
            audit=sys.audit,
            principal=principal,
            iter_meta=lambda: list(sys._mfg_meta.items()),
            telemetry=SafetyTelemetry(sys.audit),
            store=sys.kpi_materializations,
            source_ingestion_run_id="ing_1",
        )
        result = sys.kpi(principal, collection_id="manuals")

        self.assertEqual(snapshot.dagster_run_id, "dagster_kpi_1")
        self.assertEqual(result["source"], "materialized")
        self.assertEqual(result["source_ingestion_run_id"], "ing_1")
        self.assertEqual(result["dagster_run_id"], "dagster_kpi_1")
        self.assertIn("self_resolution_rate", result)

    def test_dashboard_service_does_not_require_dagster_to_read_materialized_store(self) -> None:
        sys = fresh()
        principal = claims(T, "admin", roles=("admin",))
        service = DashboardService(
            audit=sys.audit,
            get_mfg_meta=sys.get_mfg_meta,
            all_mfg_meta=lambda: list(sys._mfg_meta.items()),
            materialized_kpi_store=sys.kpi_materializations,
        )

        result = service.kpi(principal, collection_id="manuals")

        self.assertIn("materialized_at", result)
        self.assertNotEqual(result.get("source"), "dagster_request")

    def test_daily_schedule_descriptor_is_non_request_path(self) -> None:
        schedule = daily_manufacturing_dashboard_metrics_schedule()

        self.assertEqual(schedule["asset_key"], "manufacturing_dashboard_metrics")
        self.assertFalse(schedule["request_path_allowed"])
        self.assertTrue(schedule["manual_refresh_supported"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
