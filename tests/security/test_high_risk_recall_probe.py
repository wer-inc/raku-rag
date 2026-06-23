"""P1-6 / PR-009 — adversarial high-risk recall is release-gated.

The GAP-S1 failure mode is a classifier false-negative: a dangerous manufacturing question is not
classified high-risk, so the approved-citation safety gate never fires. The corpus here is synthetic
and deterministic; a miss or an all-high-risk degenerate classifier must block the eval gate.
"""

from __future__ import annotations

from types import SimpleNamespace
import unittest

from raku_rag.domain.models import ScopeType, SubjectType
from raku_rag.eval import EvaluationRunner, EvaluationSet
from raku_rag.eval.high_risk_recall import evaluate_high_risk_recall, load_high_risk_corpus
from raku_rag.eval.probes import high_risk_recall_probe
from tests.helpers import claims, fresh

T = "tenant_a"


class _AlwaysSafeClassifier:
    def classify(self, query, candidate_metadata, intent_hint=None):
        return SimpleNamespace(is_high_risk=False, reason_codes=(), classification_source=None)


class _AlwaysHighRiskClassifier:
    def classify(self, query, candidate_metadata, intent_hint=None):
        return SimpleNamespace(
            is_high_risk=True,
            reason_codes=("physical_intervention",),
            classification_source="keyword",
        )


class TestHighRiskRecallCorpus(unittest.TestCase):
    def test_default_corpus_has_positive_and_negative_controls(self) -> None:
        version, dangerous, benign = load_high_risk_corpus()
        self.assertEqual(version, "2026-06-22")
        self.assertGreaterEqual(len(dangerous), 12)
        self.assertGreaterEqual(len(benign), 7)
        self.assertTrue(all(item.query for item in dangerous + benign))

    def test_real_classifier_passes_current_adversarial_corpus(self) -> None:
        report = evaluate_high_risk_recall()
        self.assertEqual(report.leakage_count, 0, msg=str(report))
        self.assertEqual(report.missed_dangerous, ())
        self.assertEqual(report.benign_false_positive, ())


class TestHighRiskRecallProbe(unittest.TestCase):
    def test_default_probe_is_ok(self) -> None:
        result = high_risk_recall_probe()
        self.assertTrue(result.executed, msg=str(result))
        self.assertEqual(result.status, "ok", msg=str(result))
        self.assertEqual(result.leakage_count, 0)

    def test_false_negative_classifier_blocks(self) -> None:
        result = high_risk_recall_probe(_AlwaysSafeClassifier())
        self.assertTrue(result.executed, msg=str(result))
        self.assertEqual(result.status, "blocked", msg=str(result))
        self.assertGreaterEqual(result.leakage_count, 1)
        self.assertIn("missed=", result.reason)

    def test_all_high_risk_classifier_blocks_on_benign_controls(self) -> None:
        result = high_risk_recall_probe(_AlwaysHighRiskClassifier())
        self.assertTrue(result.executed, msg=str(result))
        self.assertEqual(result.status, "blocked", msg=str(result))
        self.assertGreaterEqual(result.leakage_count, 1)
        self.assertIn("false_positive=", result.reason)


class TestEvalRunnerIncludesHighRiskRecall(unittest.TestCase):
    def test_default_eval_security_checks_include_high_risk_recall(self) -> None:
        sys = fresh()
        sys.ingest_text(
            tenant_id=T,
            collection_id="c",
            document_id="d1",
            text="Backups run nightly at 02:00 UTC.",
        )
        sys.grant(T, ScopeType.COLLECTION, "c", SubjectType.USER, "alice")
        eval_set = EvaluationSet.register(
            tenant_id=T,
            items=[
                {
                    "question": "when do backups run?",
                    "expected_answer": "nightly",
                    "expected_evidence": [{"document_id": "d1"}],
                }
            ],
        )

        run = EvaluationRunner(sys).run(eval_set, principal=claims(T, "alice"), collection_id="c")

        self.assertEqual(run.gate_result, "passed")
        self.assertIn("high_risk_recall", run.security_checks)
        self.assertTrue(run.security_checks["high_risk_recall"]["passed"])


if __name__ == "__main__":
    unittest.main()
