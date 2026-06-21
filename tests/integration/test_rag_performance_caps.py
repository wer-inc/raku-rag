"""T120 - production RAG rerank/context caps."""

from __future__ import annotations

import unittest

from raku_rag.domain.models import QueryProfile, ScopeType, SubjectType
from tests.helpers import claims, fresh

T = "tenant_a"


class TestRagPerformanceCaps(unittest.TestCase):
    def setUp(self) -> None:
        self.sys = fresh()
        self.sys.grant(T, ScopeType.COLLECTION, "c", SubjectType.USER, "alice")
        self.alice = claims(T, "alice")

    def _ingest_many(self, count: int = 6) -> None:
        for index in range(count):
            self.sys.ingest_text(
                tenant_id=T,
                collection_id="c",
                document_id=f"d{index}",
                text=f"Backups run nightly at 02:00 UTC. Evidence item {index} confirms retention and operations.",
            )

    def test_rerank_input_is_capped_by_query_profile(self) -> None:
        self._ingest_many(8)
        self.sys.profiles.set(
            "c",
            QueryProfile(
                top_k=4,
                rerank_top_n=2,
                minimum_evidence_count=1,
                max_context_chunks=4,
                max_context_tokens=8000,
            ),
        )

        ans = self.sys.answer(self.alice, "when do backups run?", "c")

        self.assertEqual(ans.status, "ok")
        hot = self.sys.metrics.rag_hot_path_metrics(ans.correlation_id)[0]
        self.assertLessEqual(hot.rerank_input_count, 2)
        retrieval_span = next(
            span
            for span in self.sys.tracer.spans(correlation_id=ans.correlation_id)
            if span.name == "retrieval.retrieve"
        )
        self.assertLessEqual(int(retrieval_span.attributes["rerank_input_count"]), 2)

    def test_context_chunk_cap_limits_prompt_context(self) -> None:
        self._ingest_many(6)
        self.sys.profiles.set(
            "c",
            QueryProfile(
                top_k=5,
                rerank_top_n=5,
                minimum_evidence_count=1,
                max_context_chunks=1,
                max_context_tokens=8000,
            ),
        )

        ans = self.sys.answer(self.alice, "when do backups run?", "c")

        self.assertEqual(ans.status, "ok")
        hot = self.sys.metrics.rag_hot_path_metrics(ans.correlation_id)[0]
        self.assertEqual(hot.llm_call_count, 1)
        self.assertLessEqual(len(ans.used_chunks), 1)
        generation_span = next(
            span
            for span in self.sys.tracer.spans(correlation_id=ans.correlation_id)
            if span.name == "generation.generate"
        )
        self.assertEqual(generation_span.attributes["context_chunks"], 1)

    def test_context_token_cap_blocks_generation_when_no_evidence_fits(self) -> None:
        self.sys.ingest_text(
            tenant_id=T,
            collection_id="c",
            document_id="d1",
            text="Backups run nightly at 02:00 UTC and are retained for thirty days.",
        )
        self.sys.profiles.set(
            "c",
            QueryProfile(
                top_k=3,
                rerank_top_n=3,
                minimum_evidence_count=1,
                max_context_chunks=3,
                max_context_tokens=1,
            ),
        )

        ans = self.sys.answer(self.alice, "when do backups run?", "c")

        self.assertEqual(ans.status, "insufficient_evidence")
        self.assertFalse(
            any(
                span.name == "generation.generate"
                for span in self.sys.tracer.spans(correlation_id=ans.correlation_id)
            )
        )
        hot = self.sys.metrics.rag_hot_path_metrics(ans.correlation_id)[0]
        self.assertEqual(hot.llm_call_count, 0)
        self.assertEqual(hot.context_tokens, 0)
        events = self.sys.audit.events(T, correlation_id=ans.correlation_id)
        self.assertEqual(events[0].reason, "context_budget")


if __name__ == "__main__":
    unittest.main()
