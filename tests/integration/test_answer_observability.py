"""T034 - answer/retrieval tracing, metrics, audit, and token cost records."""

from __future__ import annotations

import unittest

from raku_rag.domain.models import ScopeType, SubjectType
from tests.helpers import claims, fresh

T = "tenant_a"


class TestAnswerObservability(unittest.TestCase):
    def setUp(self) -> None:
        self.sys = fresh()
        self.sys.ingest_text(
            tenant_id=T,
            collection_id="c",
            document_id="d1",
            text="Backups run nightly at 02:00 UTC and are retained for thirty days.",
        )
        self.sys.grant(T, ScopeType.COLLECTION, "c", SubjectType.USER, "alice")
        self.alice = claims(T, "alice")

    def test_ok_answer_records_trace_metrics_audit_and_token_costs(self) -> None:
        ans = self.sys.answer(self.alice, "when do backups run and how long are they retained?")

        self.assertEqual(ans.status, "ok")
        records = self.sys.cost.records(T)
        kinds = {record.kind for record in records}
        self.assertIn("embedding_tokens", kinds)
        self.assertIn("llm_prompt_tokens", kinds)
        self.assertIn("llm_completion_tokens", kinds)
        token_records = [record for record in records if record.unit == "tokens"]
        self.assertTrue(token_records)
        self.assertTrue(all(record.trace_id == ans.correlation_id for record in token_records))
        self.assertTrue(all(not record.billable for record in token_records))
        self.assertEqual(ans.cost["tenant_total"], 1.0)

        self.assertEqual(
            self.sys.metrics.counter(
                "answer_requests_total",
                labels={"tenant_id": T, "profile_id": "default", "status": "ok"},
            ),
            1.0,
        )
        self.assertEqual(
            self.sys.metrics.counter(
                "retrieval_requests_total",
                labels={"tenant_id": T, "profile_id": "default"},
            ),
            1.0,
        )
        spans = self.sys.tracer.spans(correlation_id=ans.correlation_id)
        self.assertEqual(
            {span.name for span in spans},
            {"answer.answer", "retrieval.retrieve", "generation.generate"},
        )
        self.assertTrue(all(span.status == "ok" for span in spans))

        events = self.sys.audit.events(T, correlation_id=ans.correlation_id)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].action, "answer")
        self.assertEqual(events[0].decision, "ok")
        self.assertEqual(events[0].document_ids, ("d1",))
        self.assertEqual(events[0].chunk_ids, tuple(ans.used_chunks))
        self.assertNotIn("when do backups", repr(events[0]))

    def test_budget_exceeded_records_metric_and_audit_without_token_costs(self) -> None:
        self.sys.cost.set_budget(T, 0.5)

        ans = self.sys.answer(self.alice, "when do backups run?")

        self.assertEqual(ans.status, "budget_exceeded")
        self.assertEqual(self.sys.cost.records(T), ())
        self.assertEqual(
            self.sys.metrics.counter(
                "answer_requests_total",
                labels={"tenant_id": T, "profile_id": "default", "status": "budget_exceeded"},
            ),
            1.0,
        )
        events = self.sys.audit.events(T, correlation_id=ans.correlation_id)
        self.assertEqual(events[0].decision, "budget_exceeded")
        self.assertEqual(events[0].reason, "budget")


if __name__ == "__main__":
    unittest.main()
