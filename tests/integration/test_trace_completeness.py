"""T062 - SC-005 trace completeness for ingestion, search, and answer."""

from __future__ import annotations

import unittest

from raku_rag.domain.models import ScopeType, SubjectType
from tests.helpers import claims, fresh

T = "tenant_a"


class TestTraceCompleteness(unittest.TestCase):
    def setUp(self) -> None:
        self.sys = fresh()
        self.alice = claims(T, "alice")

    def test_ingestion_search_and_answer_have_required_spans(self) -> None:
        job = self.sys.ingest_text(
            tenant_id=T,
            collection_id="manuals",
            source_id="upload",
            document_id="backup",
            text="Backups run nightly at 02:00 UTC.",
        )
        self.sys.grant(T, ScopeType.COLLECTION, "manuals", SubjectType.USER, "alice")

        ingest_report = self.sys.tracer.verify_completeness(
            job.correlation_id, ("ingestion.ingest",)
        )
        self.assertTrue(ingest_report.complete, ingest_report.missing_spans)

        search_correlation_id = "trace_search_complete"
        results = self.sys.search(
            self.alice,
            "when do backups run?",
            "manuals",
            correlation_id=search_correlation_id,
        )
        search_report = self.sys.tracer.verify_completeness(
            search_correlation_id, ("retrieval.retrieve",)
        )
        self.assertTrue(results)
        self.assertTrue(search_report.complete, search_report.missing_spans)

        answer = self.sys.answer(self.alice, "when do backups run?", "manuals")
        answer_report = self.sys.tracer.verify_completeness(
            answer.correlation_id,
            ("answer.answer", "retrieval.retrieve", "generation.generate"),
        )

        self.assertEqual(answer.status, "ok")
        self.assertTrue(answer_report.complete, answer_report.missing_spans)
        for span in self.sys.tracer.spans(correlation_id=answer.correlation_id):
            self.assertEqual(span.tenant_id, T)
            self.assertNotIn("when do backups", repr(span.attributes))
            self.assertNotIn("Backups run nightly", repr(span.attributes))


if __name__ == "__main__":
    unittest.main()
