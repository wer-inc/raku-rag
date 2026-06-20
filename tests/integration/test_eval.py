"""T054/T056/T057 - text evaluation metrics and redacted registration."""

from __future__ import annotations

import unittest

from raku_rag.domain.models import ScopeType, SubjectType
from raku_rag.eval import EvaluationRunner, EvaluationSet
from tests.helpers import claims, fresh

T = "tenant_a"


class TestEvaluationRunner(unittest.TestCase):
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

    def test_eval_run_calculates_text_metrics_latency_and_cost(self) -> None:
        eval_set = EvaluationSet.register(
            tenant_id=T,
            items=[
                {
                    "question": "when do backups run and how long are they retained?",
                    "expected_answer": "nightly at 02:00 UTC; thirty days",
                    "expected_evidence": [{"document_id": "d1"}],
                }
            ],
        )

        run = EvaluationRunner(self.sys).run(eval_set, principal=self.alice, collection_id="c")

        self.assertEqual(run.status, "succeeded")
        self.assertEqual(run.gate_result, "passed")
        self.assertEqual(run.metrics["recall_at_k"], 1.0)
        self.assertEqual(run.metrics["citation_accuracy"], 1.0)
        self.assertEqual(run.metrics["groundedness"], 1.0)
        self.assertGreaterEqual(run.metrics["p95_latency_ms"], 0.0)
        self.assertGreater(run.metrics["query_cost"], 0.0)
        self.assertEqual(run.security_checks["acl_leakage"]["passed"], True)

    def test_eval_set_registration_scrubs_pii_and_secrets(self) -> None:
        eval_set = EvaluationSet.register(
            tenant_id=T,
            items=[
                {
                    "question": "Email alice@example.com and use sk-ABCDEFGH123456 for backups?",
                    "expected_answer": "Contact alice@example.com",
                    "expected_evidence": ["d1"],
                }
            ],
        )

        item = eval_set.items[0]
        self.assertNotIn("alice@example.com", item.question)
        self.assertNotIn("sk-ABCDEFGH123456", item.question)
        self.assertIn("[REDACTED:email]", item.question)
        self.assertIn("[REDACTED:api_key]", item.question)
        self.assertNotIn("alice@example.com", item.expected_answer)


if __name__ == "__main__":
    unittest.main()
