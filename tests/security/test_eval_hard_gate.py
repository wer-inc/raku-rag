"""T055 - evaluation security checks are absolute hard gates."""

from __future__ import annotations

import unittest

from raku_rag.domain.models import ScopeType, SubjectType
from raku_rag.eval import EvaluationRunner, EvaluationSet
from raku_rag.eval.runner import SECURITY_CHECKS
from tests.helpers import claims, fresh

T = "tenant_a"


class TestEvaluationHardGate(unittest.TestCase):
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
        self.eval_set = EvaluationSet.register(
            tenant_id=T,
            items=[
                {
                    "question": "when do backups run?",
                    "expected_answer": "nightly",
                    "expected_evidence": [{"document_id": "d1"}],
                }
            ],
        )

    def test_any_security_violation_blocks_gate_result(self) -> None:
        for check_name in SECURITY_CHECKS:
            with self.subTest(check_name=check_name):
                run = EvaluationRunner(self.sys).run(
                    self.eval_set,
                    principal=self.alice,
                    collection_id="c",
                    security_check_counts={check_name: 1},
                )

                self.assertEqual(run.gate_result, "blocked")
                self.assertFalse(run.security_checks[check_name]["passed"])
                self.assertEqual(run.security_checks[check_name]["count"], 1)


if __name__ == "__main__":
    unittest.main()
