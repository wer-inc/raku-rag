from __future__ import annotations

import unittest

from raku_rag.dagster.jobs.evaluation import build_evaluation_job_request, execute_evaluation_job
from raku_rag.domain.models import ScopeType, SubjectType
from raku_rag.eval import EvaluationRunner, EvaluationSet
from tests.helpers import claims, fresh


class EvaluationJobTest(unittest.TestCase):
    def test_builds_dagster_compatible_evaluation_request_and_executes(self) -> None:
        sys = fresh()
        sys.ingest_text(
            tenant_id="tenant_a",
            collection_id="c",
            document_id="d1",
            text="Backups run nightly at 02:00 UTC and are retained for thirty days.",
        )
        sys.grant("tenant_a", ScopeType.COLLECTION, "c", SubjectType.USER, "alice")
        eval_set = EvaluationSet.register(
            tenant_id="tenant_a",
            eval_set_id="eval-set-1",
            items=[
                {
                    "question": "when do backups run?",
                    "expected_answer": "nightly",
                    "expected_evidence": [{"document_id": "d1"}],
                }
            ],
        )

        req = build_evaluation_job_request(eval_set, baseline=True, collection_id="c")
        run = execute_evaluation_job(
            EvaluationRunner(sys),
            eval_set,
            principal=claims("tenant_a", "alice"),
            collection_id=req.collection_id,
            baseline=req.baseline,
        )

        self.assertEqual(req.eval_set_id, "eval-set-1")
        self.assertTrue(req.baseline)
        self.assertEqual(req.dagster_tags["job_type"], "evaluation")
        self.assertEqual(run.status, "succeeded")
        self.assertTrue(run.baseline)


if __name__ == "__main__":
    unittest.main()
