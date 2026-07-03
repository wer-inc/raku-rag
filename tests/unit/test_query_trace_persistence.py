"""★G1 — durable per-query telemetry seams (cost / query-trace / rerank-trace sinks).

Contract under test: every sink is write-through and FAIL-OPEN — a sink outage degrades to the
existing in-memory behavior and never breaks retrieval/answering — and the durable rows stay
reference-only (hashed identities, no raw query/answer text on the trace record itself).
"""

from __future__ import annotations

import unittest

from raku_rag.app import MvpSystem
from raku_rag.domain.models import QueryProfile, ScopeType, SubjectType
from raku_rag.observability.metrics import MetricsRecorder
from raku_rag.persistence.telemetry import cost_record_scope
from raku_rag.services.cost import CostService
from raku_rag.services.retrieval import RetrievalService
from tests.helpers import claims


class _RecordingSink:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list = []

    def record(self, *args, **kwargs) -> None:
        if self.fail:
            raise RuntimeError("sink down")
        self.calls.append((args, kwargs))


class CostSinkTest(unittest.TestCase):
    def test_record_writes_through_to_sink(self) -> None:
        sink = _RecordingSink()
        cost = CostService(sink=sink)
        cost.record("tenant_a", 1.5, kind="query", trace_id="cid-1", query_id="default")
        self.assertEqual(len(sink.calls), 1)
        (record,), _ = sink.calls[0]
        self.assertEqual(record.tenant_id, "tenant_a")
        self.assertEqual(record.trace_id, "cid-1")

    def test_sink_failure_keeps_in_memory_record_and_budget(self) -> None:
        cost = CostService(sink=_RecordingSink(fail=True))
        cost.set_budget("tenant_a", 10.0)
        result = cost.record("tenant_a", 2.0)
        self.assertEqual(result["tenant_total"], 2.0)
        self.assertEqual(len(cost.records("tenant_a")), 1)
        self.assertEqual(cost.sink_failures, 1)
        self.assertFalse(cost.would_exceed("tenant_a", 1.0))

    def test_scope_mapping_prefers_most_specific(self) -> None:
        base = dict(tenant_id="t", kind="query", amount=0.0)
        from raku_rag.services.cost import CostRecord

        self.assertEqual(
            cost_record_scope(CostRecord(query_id="q1", collection_id="c1", **base)),
            ("query", "q1"),
        )
        self.assertEqual(cost_record_scope(CostRecord(job_id="j1", **base)), ("job", "j1"))
        self.assertEqual(
            cost_record_scope(CostRecord(collection_id="c1", **base)), ("collection", "c1")
        )
        self.assertEqual(cost_record_scope(CostRecord(**base)), ("tenant", "t"))


class QueryTraceSinkTest(unittest.TestCase):
    def test_hot_path_metric_reaches_sink_with_raw_tenant_and_hashed_identity(self) -> None:
        sink = _RecordingSink()
        metrics = MetricsRecorder(hot_path_sink=sink)
        metric = metrics.record_rag_hot_path(
            request_id="req-1",
            tenant_id="tenant_a",
            user_id="alice",
            profile_id="default",
            status="ok",
            total_ms=12.0,
            model="cohere-answer-model",
            prompt_version="grounded/v1",
        )
        self.assertEqual(len(sink.calls), 1)
        (tenant_id, sunk_metric), _ = sink.calls[0]
        # Raw tenant_id goes to the sink (RLS needs it); the metric itself stays hashed.
        self.assertEqual(tenant_id, "tenant_a")
        self.assertNotEqual(sunk_metric.tenant_id_hash, "tenant_a")
        self.assertNotEqual(sunk_metric.user_id_hash, "alice")
        self.assertEqual(sunk_metric.model, "cohere-answer-model")
        self.assertEqual(sunk_metric.prompt_version, "grounded/v1")
        self.assertEqual(metric, sunk_metric)

    def test_sink_failure_is_metered_not_raised(self) -> None:
        metrics = MetricsRecorder(hot_path_sink=_RecordingSink(fail=True))
        metric = metrics.record_rag_hot_path(
            request_id="req-1",
            tenant_id="tenant_a",
            user_id="alice",
            profile_id="default",
            status="ok",
        )
        self.assertEqual(metrics.rag_hot_path_metrics("req-1"), (metric,))
        self.assertEqual(
            metrics.counter(
                "query_trace_persist_failures_total",
                labels={"tenant_id_hash": metric.tenant_id_hash},
            ),
            1.0,
        )

    def test_answer_hot_path_carries_model_and_prompt_version(self) -> None:
        system = MvpSystem()
        system.ingest_text(
            tenant_id="tenant_a",
            collection_id="manuals",
            document_id="doc_a",
            text="The maintenance interval for pump P-12 is ninety days per the manual.",
        )
        system.grant("tenant_a", ScopeType.COLLECTION, "manuals", SubjectType.USER, "alice")
        ans = system.answer(claims("tenant_a", "alice"), "maintenance interval for pump P-12?")
        hot = system.metrics.rag_hot_path_metrics(ans.correlation_id)[0]
        self.assertEqual(hot.model, getattr(system.llm, "model", ""))


class RerankTraceSinkTest(unittest.TestCase):
    def _retrieval_with_sink(self, sink) -> tuple[MvpSystem, RetrievalService]:
        system = MvpSystem()
        system.ingest_text(
            tenant_id="tenant_a",
            collection_id="manuals",
            document_id="doc_a",
            text="Pump P-12 alarm E-152 requires a reset after inspection.",
        )
        system.grant("tenant_a", ScopeType.COLLECTION, "manuals", SubjectType.USER, "alice")
        retrieval = RetrievalService(
            system.store,
            system.embedder,
            system.acl,
            system.reranker,
            system.cost,
            system.metrics,
            system.tracer,
            rerank_trace_sink=sink,
        )
        return system, retrieval

    def test_executed_rerank_is_traced(self) -> None:
        sink = _RecordingSink()
        _, retrieval = self._retrieval_with_sink(sink)
        results = retrieval.retrieve(
            claims("tenant_a", "alice"),
            "pump P-12 alarm",
            QueryProfile(),
            correlation_id="cid-1",
        )
        self.assertTrue(results)
        self.assertEqual(len(sink.calls), 1)
        _, kwargs = sink.calls[0]
        self.assertEqual(kwargs["tenant_id"], "tenant_a")
        self.assertEqual(kwargs["query_id"], "cid-1")
        self.assertEqual(kwargs["provider"], "ScoreOrderReranker")
        self.assertEqual(kwargs["final_context_count"], len(results))
        self.assertGreaterEqual(kwargs["candidate_count"], len(results))

    def test_skipped_rerank_is_not_traced(self) -> None:
        sink = _RecordingSink()
        _, retrieval = self._retrieval_with_sink(sink)
        retrieval.retrieve(
            claims("tenant_a", "alice"),
            "pump P-12 alarm",
            QueryProfile(rerank_enabled=False),
            correlation_id="cid-2",
        )
        self.assertEqual(sink.calls, [])

    def test_sink_failure_never_breaks_retrieval(self) -> None:
        system, retrieval = self._retrieval_with_sink(_RecordingSink(fail=True))
        results = retrieval.retrieve(
            claims("tenant_a", "alice"),
            "pump P-12 alarm",
            QueryProfile(),
            correlation_id="cid-3",
        )
        self.assertTrue(results)
        self.assertEqual(
            system.metrics.counter(
                "rerank_trace_persist_failures_total",
                labels={"tenant_id": "tenant_a", "profile_id": "default"},
            ),
            1.0,
        )


if __name__ == "__main__":
    unittest.main()
