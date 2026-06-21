"""P1-8 / PR-006 — retrieval failures are observable, never silent.

Pins that a rerank exception is logged + metered + recorded on the span (fail-safe fallback still
returns results), and that an empty retrieval is attributable: ``last_prefiltered_count`` and a
root-cause ``retrieval_outcome`` are exported so ops can tell "ACL/tenant removed all candidates"
from "candidates passed the pre-filter but none survived".
"""

from __future__ import annotations

import unittest

from raku_rag.domain.models import QueryProfile, ScopeType, SubjectType
from raku_rag.observability.metrics import MetricsRecorder
from raku_rag.observability.tracing import InMemoryTracer
from raku_rag.services.retrieval import RetrievalService
from tests.helpers import claims, fresh

T = "tenant_a"


class _FailingReranker:
    def rerank(self, query, candidates, limit):
        raise RuntimeError("rerank backend down")


class TestRetrievalFailureLogging(unittest.TestCase):
    def setUp(self) -> None:
        self.sys = fresh()
        self.sys.ingest_text(
            tenant_id=T,
            collection_id="c",
            document_id="d1",
            text="The maintenance interval for pump P-12 is ninety days.",
        )
        self.sys.grant(T, ScopeType.COLLECTION, "c", SubjectType.USER, "alice")
        self.alice = claims(T, "alice")
        self.metrics = MetricsRecorder()
        self.tracer = InMemoryTracer()

    def _service(self, reranker):
        return RetrievalService(
            self.sys.store,
            self.sys.embedder,
            self.sys.acl,
            reranker=reranker,
            metrics=self.metrics,
            tracer=self.tracer,
        )

    def _span(self, cid):
        spans = [s for s in self.tracer.spans(correlation_id=cid) if s.name == "retrieval.retrieve"]
        self.assertEqual(len(spans), 1)
        return spans[0]

    def test_rerank_failure_is_recorded_not_silent(self) -> None:
        svc = self._service(_FailingReranker())
        profile = QueryProfile(rerank_enabled=True)
        result = svc.retrieve(
            self.alice, "pump P-12 maintenance interval", profile, correlation_id="cid1"
        )
        self.assertTrue(result, "rerank failure must fall back to results, not return empty")
        labels = {"tenant_id": T, "profile_id": profile.profile_id}
        self.assertGreaterEqual(
            self.metrics.counter("retrieval_rerank_failures_total", labels=labels), 1
        )
        span = self._span("cid1")
        self.assertEqual(span.attributes.get("rerank_status"), "failed")
        self.assertEqual(span.attributes.get("rerank_error"), "RuntimeError")

    def test_acl_emptied_retrieval_is_attributable(self) -> None:
        svc = self._service(None)
        profile = QueryProfile()
        bob = claims(T, "bob")  # NOT granted collection "c" → pre-filter removes everything
        result = svc.retrieve(bob, "pump P-12 maintenance interval", profile, correlation_id="cid2")
        self.assertEqual(result, [])
        span = self._span("cid2")
        self.assertEqual(span.attributes.get("retrieval_outcome"), "no_visible_candidates")
        self.assertEqual(span.attributes.get("prefiltered_count"), 0)
        self.assertGreaterEqual(
            self.metrics.counter(
                "retrieval_empty_total",
                labels={
                    "tenant_id": T,
                    "profile_id": profile.profile_id,
                    "outcome": "no_visible_candidates",
                },
            ),
            1,
        )

    def test_successful_retrieval_reports_ok_outcome(self) -> None:
        svc = self._service(None)
        profile = QueryProfile()
        result = svc.retrieve(
            self.alice, "pump P-12 maintenance interval", profile, correlation_id="cid3"
        )
        self.assertTrue(result)
        span = self._span("cid3")
        self.assertEqual(span.attributes.get("retrieval_outcome"), "ok")
        self.assertGreaterEqual(span.attributes.get("prefiltered_count"), 1)


if __name__ == "__main__":
    unittest.main()
