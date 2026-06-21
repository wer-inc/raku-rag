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


    def test_rag_hot_path_metrics_hash_identity_and_record_required_fields(self) -> None:
        metrics = MetricsRecorder()

        metric = metrics.record_rag_hot_path(
            request_id="req_1",
            tenant_id="tenant_secret",
            user_id="alice_secret",
            profile_id="default",
            status="ok",
            llm_call_count=1,
            retrieval_ms=12.5,
            rerank_ms=3.0,
            generation_ms=40.0,
            total_ms=60.0,
            retrieved_chunks=4,
            rerank_input_count=20,
            context_tokens=1200,
            prompt_tokens=1300,
            completion_tokens=80,
            cache_hit=False,
        )

        self.assertEqual(metric.request_id, "req_1")
        self.assertNotEqual(metric.tenant_id_hash, "tenant_secret")
        self.assertNotEqual(metric.user_id_hash, "alice_secret")
        self.assertNotIn("tenant_secret", repr(metric))
        self.assertNotIn("alice_secret", repr(metric))
        self.assertEqual(metrics.rag_hot_path_metrics("req_1"), (metric,))
        labels = {
            "tenant_id_hash": metric.tenant_id_hash,
            "profile_id": "default",
            "status": "ok",
            "cache_hit": "false",
        }
        self.assertEqual(metrics.counter("rag_requests_total", labels=labels), 1.0)
        self.assertEqual(metrics.observations("rag_rerank_input_count", labels=labels), (20,))
        self.assertEqual(metrics.observations("rag_prompt_tokens", labels=labels), (1300,))


if __name__ == "__main__":
    unittest.main()
