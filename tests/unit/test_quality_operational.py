"""★G3b/★G5 — 実測運用メトリクス seams (query_redacted on traces + operational summary reader).

Contracts under test:
- The hot-path metric stores the question ONLY after PII redaction (services/answer.py runs the
  Redactor before MetricsRecorder ever sees the text) — same stance as hashed identities.
- InMemoryQueryTraceReader.operational_summary computes the same shape as the Postgres reader
  (p50/p95 via percentile_cont semantics, status breakdown, insufficient_rate, newest-first
  refusal drill-down) and filters tenants via the tenant_id_hash the metric stores.
"""

from __future__ import annotations

import unittest

from raku_rag.app import MvpSystem
from raku_rag.domain.models import ScopeType, SubjectType
from raku_rag.observability.metrics import MetricsRecorder
from raku_rag.persistence.telemetry import InMemoryQueryTraceReader, _percentile_cont
from tests.helpers import claims


def _record(metrics: MetricsRecorder, tenant: str, request_id: str, status: str, **kwargs) -> None:
    metrics.record_rag_hot_path(
        request_id=request_id,
        tenant_id=tenant,
        user_id="alice",
        profile_id="default",
        status=status,
        **kwargs,
    )


class InMemoryOperationalSummaryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.metrics = MetricsRecorder()
        self.reader = InMemoryQueryTraceReader(self.metrics)

    def test_aggregates_latency_status_and_tokens(self) -> None:
        _record(
            self.metrics,
            "tenant_a",
            "r1",
            "ok",
            total_ms=100,
            prompt_tokens=10,
            completion_tokens=5,
        )
        _record(
            self.metrics,
            "tenant_a",
            "r2",
            "ok",
            total_ms=200,
            prompt_tokens=20,
            completion_tokens=5,
        )
        _record(
            self.metrics,
            "tenant_a",
            "r3",
            "insufficient_evidence",
            total_ms=300,
            query_redacted="ポンプ P-99 の交換周期は?",
        )
        _record(self.metrics, "tenant_a", "r4", "budget_exceeded", total_ms=400)

        summary = self.reader.operational_summary("tenant_a")
        self.assertEqual(summary["query_count"], 4)
        # percentile_cont (linear interpolation) semantics, matching the Postgres reader's SQL.
        self.assertAlmostEqual(summary["p50_ms"], 250.0)
        self.assertAlmostEqual(summary["p95_ms"], 385.0)
        self.assertAlmostEqual(summary["avg_total_tokens"], (15 + 25 + 0 + 0) / 4)
        self.assertEqual(
            summary["status_counts"],
            {"ok": 2, "insufficient_evidence": 1, "budget_exceeded": 1},
        )
        self.assertAlmostEqual(summary["insufficient_rate"], 0.25)

    def test_refusal_drilldown_is_newest_first_non_ok_with_query_text(self) -> None:
        _record(self.metrics, "tenant_a", "r1", "ok", query_redacted="answered")
        _record(
            self.metrics,
            "tenant_a",
            "r2",
            "insufficient_evidence",
            query_redacted="older refusal",
        )
        _record(self.metrics, "tenant_a", "r3", "llm_unavailable", query_redacted="newer refusal")

        refusals = self.reader.operational_summary("tenant_a")["recent_refusals"]
        self.assertEqual([r["request_id"] for r in refusals], ["r3", "r2"])
        self.assertEqual(refusals[0]["query_redacted"], "newer refusal")
        self.assertEqual(refusals[0]["status"], "llm_unavailable")
        # In-memory metrics carry no timestamp; the shape still includes created_at.
        self.assertEqual(refusals[0]["created_at"], "")
        limited = self.reader.operational_summary("tenant_a", limit=1)["recent_refusals"]
        self.assertEqual([r["request_id"] for r in limited], ["r3"])

    def test_tenants_are_isolated_via_identity_hash(self) -> None:
        _record(self.metrics, "tenant_a", "ra", "ok", total_ms=100)
        _record(self.metrics, "tenant_b", "rb", "insufficient_evidence", total_ms=999)

        summary_a = self.reader.operational_summary("tenant_a")
        self.assertEqual(summary_a["query_count"], 1)
        self.assertEqual(summary_a["status_counts"], {"ok": 1})
        self.assertEqual(summary_a["recent_refusals"], [])
        summary_b = self.reader.operational_summary("tenant_b")
        self.assertEqual(summary_b["query_count"], 1)
        self.assertEqual([r["request_id"] for r in summary_b["recent_refusals"]], ["rb"])

    def test_empty_tenant_yields_zeroed_shape(self) -> None:
        summary = self.reader.operational_summary("tenant_empty")
        self.assertEqual(
            summary,
            {
                "query_count": 0,
                "p50_ms": 0.0,
                "p95_ms": 0.0,
                "avg_total_tokens": 0.0,
                "status_counts": {},
                "insufficient_rate": 0.0,
                "recent_refusals": [],
            },
        )

    def test_percentile_cont_matches_postgres_semantics(self) -> None:
        self.assertEqual(_percentile_cont([], 0.95), 0.0)
        self.assertEqual(_percentile_cont([42.0], 0.95), 42.0)
        self.assertAlmostEqual(_percentile_cont([100, 200, 300, 400], 0.5), 250.0)
        self.assertAlmostEqual(_percentile_cont([100, 200, 300, 400], 0.95), 385.0)


class QueryRedactionOnTraceTest(unittest.TestCase):
    """The answer path must mask PII BEFORE the metric stores the question (★G3b stance)."""

    def _system(self) -> MvpSystem:
        system = MvpSystem()
        system.ingest_text(
            tenant_id="tenant_a",
            collection_id="manuals",
            document_id="doc_a",
            text="The maintenance interval for pump P-12 is ninety days per the manual.",
        )
        system.grant("tenant_a", ScopeType.COLLECTION, "manuals", SubjectType.USER, "alice")
        return system

    def test_query_with_email_and_phone_is_masked_before_storage(self) -> None:
        system = self._system()
        ans = system.answer(
            claims("tenant_a", "alice"),
            "maintenance interval for pump P-12? contact alice@example.com or 03-1234-5678",
        )
        metric = system.metrics.rag_hot_path_metrics(ans.correlation_id)[0]
        self.assertNotIn("alice@example.com", metric.query_redacted)
        self.assertNotIn("03-1234-5678", metric.query_redacted)
        self.assertIn("[REDACTED:email]", metric.query_redacted)
        self.assertIn("[REDACTED:jp_phone]", metric.query_redacted)
        # The non-PII part of the question survives for 未回答分析.
        self.assertIn("pump P-12", metric.query_redacted)

    def test_durable_sink_receives_the_already_redacted_metric(self) -> None:
        class _RecordingSink:
            def __init__(self) -> None:
                self.calls: list = []

            def record(self, tenant_id, metric) -> None:
                self.calls.append((tenant_id, metric))

        system = self._system()
        sink = _RecordingSink()
        system.metrics.hot_path_sink = sink
        ans = system.answer(
            claims("tenant_a", "alice"),
            "maintenance interval for pump P-12? reach me at alice@example.com",
        )
        metric = system.metrics.rag_hot_path_metrics(ans.correlation_id)[0]
        self.assertIn("maintenance interval", metric.query_redacted)
        # The durable sink receives the SAME already-redacted metric (never the raw query).
        sunk = [m for _tenant, m in sink.calls if m.request_id == ans.correlation_id]
        self.assertEqual(len(sunk), 1)
        self.assertNotIn("alice@example.com", sunk[0].query_redacted)


if __name__ == "__main__":
    unittest.main()
