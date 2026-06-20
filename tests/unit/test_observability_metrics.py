from __future__ import annotations

import json
import unittest
from pathlib import Path

from raku_rag.observability.metrics import MetricsRecorder, OBSERVABILITY_STAGES

ROOT = Path(__file__).resolve().parents[2]


class TestObservabilityMetrics(unittest.TestCase):
    def test_stage_summary_covers_latency_throughput_error_and_cost(self) -> None:
        metrics = MetricsRecorder()

        metrics.record_stage(
            "ingestion", tenant_id="tenant_a", status="succeeded", latency_ms=10.0, cost=0.25
        )
        metrics.record_stage("ingestion", tenant_id="tenant_a", status="failed", latency_ms=30.0)

        summary = metrics.stage_summary("tenant_a", "ingestion")

        self.assertEqual(summary.stage, "ingestion")
        self.assertEqual(summary.throughput, 2.0)
        self.assertEqual(summary.error_count, 1.0)
        self.assertEqual(summary.error_rate, 0.5)
        self.assertEqual(summary.p95_latency_ms, 30.0)
        self.assertEqual(summary.cost_total, 0.25)

    def test_dashboard_definition_publishes_required_stage_panels(self) -> None:
        dashboard = json.loads(
            (ROOT / "ops/dashboards/rag-platform-observability.json").read_text()
        )
        metrics = {panel["metric"] for panel in dashboard["panels"]}

        self.assertEqual(tuple(dashboard["stages"]), OBSERVABILITY_STAGES)
        self.assertIn("rag_stage_latency_ms", metrics)
        self.assertIn("rag_stage_throughput_total", metrics)
        self.assertIn("rag_stage_errors_total", metrics)
        self.assertIn("rag_stage_cost_total", metrics)


if __name__ == "__main__":
    unittest.main()
