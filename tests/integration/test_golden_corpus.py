"""012 (P1-5) US3 — golden corpus regression gate against a COMMITTED deterministic baseline.

Closes the eval-harness "regression gate is weak" gap (audit PR-008): a representative per-industry
corpus is run against a *committed* baseline (never `baseline_from_run`), and a seeded quality drop
fails the gate. The final test proves the loophole is closed: a self-derived baseline MISSES a
precision/MRR/faithfulness regression that the committed baseline catches.
"""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import unittest

from raku_rag.domain.models import IdentityClaims, ScopeType, SubjectType
from raku_rag.eval import (
    EvaluationBaseline,
    EvaluationRunner,
    EvaluationSet,
    evaluate_baseline_gate,
)
from raku_rag.eval.baseline import DEFAULT_MIN_METRICS

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
_CORPUS = _FIXTURES / "uat" / "golden_corpus.json"
_BASELINE = _FIXTURES / "eval" / "golden_baseline.json"
_QUALITY_FLOORS = (
    "recall_at_k",
    "precision_at_k",
    "mrr",
    "citation_accuracy",
    "groundedness",
    "faithfulness",
)


def _load_corpus():
    return json.loads(_CORPUS.read_text(encoding="utf-8"))


def _committed_baseline() -> EvaluationBaseline:
    data = json.loads(_BASELINE.read_text(encoding="utf-8"))
    return EvaluationBaseline(
        metrics={k: float(v) for k, v in data["metrics"].items()},
        min_metrics={k: float(v) for k, v in data["min_metrics"].items()},
        max_metrics={k: float(v) for k, v in data["max_metrics"].items()},
        security_checks=tuple(data.get("security_checks", ())),
        version_registry=dict(data.get("version_registry") or {}),
    )


def _build_system_and_set(corpus):
    from raku_rag.app import MvpSystem

    tenant = corpus["tenant_id"]
    user = corpus["principal_user"]
    sys = MvpSystem()
    items: list = []
    expected_doc_ids: list = []
    for industry in corpus["industries"].values():
        collection_id = industry["collection_id"]
        for doc in industry["documents"]:
            sys.ingest_text(
                tenant_id=tenant,
                collection_id=collection_id,
                document_id=doc["document_id"],
                text=doc["text"],
            )
        sys.grant(tenant, ScopeType.COLLECTION, collection_id, SubjectType.USER, user)
        for item in industry["items"]:
            items.append(item)
            # ★G2: unanswerable items carry no gold evidence by design.
            expected_doc_ids.extend(e["document_id"] for e in item.get("expected_evidence") or ())
    eval_set = EvaluationSet.register(tenant_id=tenant, items=items)
    principal = IdentityClaims(tenant_id=tenant, user_id=user)
    return sys, eval_set, principal, tenant, expected_doc_ids


class TestGoldenCorpusBaseline(unittest.TestCase):
    def setUp(self) -> None:
        self.corpus = _load_corpus()
        self.sys, self.eval_set, self.principal, self.tenant, self.expected = _build_system_and_set(
            self.corpus
        )
        self.baseline = _committed_baseline()

    def test_corpus_is_representative_multi_industry(self) -> None:
        self.assertEqual(
            set(self.corpus["industries"]), {"manufacturing", "real_estate", "investment"}
        )
        self.assertGreaterEqual(len(self.eval_set.items), 15)

    def test_run_passes_committed_baseline(self) -> None:
        run = EvaluationRunner(self.sys).run(self.eval_set, principal=self.principal)
        self.assertEqual(run.gate_result, "passed")
        self.assertTrue(run.probes_executed)
        result = evaluate_baseline_gate(run, self.baseline)
        self.assertTrue(result.passed, msg=f"failures={result.failures}")
        # The baseline is COMMITTED (loaded from fixture), not derived from this run.
        for key in _QUALITY_FLOORS:
            self.assertIn(key, self.baseline.min_metrics)
        self.assertEqual(run.version_registry, self.baseline.version_registry)

    def test_version_registry_mismatch_fails_gate(self) -> None:
        run = EvaluationRunner(self.sys).run(self.eval_set, principal=self.principal)
        mismatched = EvaluationBaseline(
            metrics=self.baseline.metrics,
            min_metrics=self.baseline.min_metrics,
            max_metrics=self.baseline.max_metrics,
            security_checks=self.baseline.security_checks,
            version_registry={**self.baseline.version_registry, "dataset_version": "dataset_old"},
        )
        result = evaluate_baseline_gate(run, mismatched)
        self.assertFalse(result.passed)
        self.assertTrue(
            any("version_registry.dataset_version" in failure for failure in result.failures),
            msg=str(result.failures),
        )

    def test_seeded_doc_removal_regresses_and_fails_gate(self) -> None:
        # Authentic end-to-end regression: tombstone one expected doc → its item can no longer be
        # retrieved → recall/precision/mrr drop below the committed floors → the gate fails.
        victim = self.expected[0]
        self.sys.deletion.delete(self.tenant, victim)
        run = EvaluationRunner(self.sys).run(self.eval_set, principal=self.principal)
        self.assertLess(run.metrics["recall_at_k"], 1.0)
        result = evaluate_baseline_gate(run, self.baseline)
        self.assertFalse(result.passed)
        self.assertTrue(any("recall_at_k" in f for f in result.failures), msg=str(result.failures))

    def test_seeded_metric_regression_fails_for_each_quality_metric(self) -> None:
        run = EvaluationRunner(self.sys).run(self.eval_set, principal=self.principal)
        for metric in ("precision_at_k", "mrr", "faithfulness", "claim_groundedness"):
            with self.subTest(metric=metric):
                floor = self.baseline.min_metrics[metric]
                degraded = replace(run, metrics={**run.metrics, metric: floor - 0.1})
                result = evaluate_baseline_gate(degraded, self.baseline)
                self.assertFalse(result.passed)
                self.assertTrue(any(metric in f for f in result.failures), msg=str(result.failures))

    def test_unanswerable_slice_is_represented(self) -> None:
        # ★G2 (goal.md §2-1): the release corpus must carry must-refuse items, including a
        # high-risk one, so "cannot say I don't know" regressions are visible to the gate.
        unanswerable = [i for i in self.eval_set.items if not i.is_answerable]
        self.assertGreaterEqual(len(unanswerable), 5)
        self.assertGreaterEqual(sum(1 for i in unanswerable if i.risk_level == "high"), 1)
        self.assertGreaterEqual(
            sum(1 for i in unanswerable if i.category == "unanswerable_in_domain"), 2
        )

    def test_refusal_and_risk_regressions_fail_gate(self) -> None:
        # ★G2 ratchet mechanics: worsening any refusal/risk metric beyond the committed values
        # blocks the release, exactly like the quality-metric floors above.
        run = EvaluationRunner(self.sys).run(self.eval_set, principal=self.principal)
        seeded = {
            "unanswerable_answer_rate": 0.5,  # above the 0.29 ratchet ceiling
            "over_refusal_rate": 0.1,  # above the 0.0 ceiling
            "refusal_accuracy": 0.8,  # below the 0.92 floor
            "risk_weighted_score": 0.7,  # below the 0.86 floor
            "high_risk_recall": 0.9,  # below the 1.0 floor
        }
        for metric, bad_value in seeded.items():
            with self.subTest(metric=metric):
                degraded = replace(run, metrics={**run.metrics, metric: bad_value})
                result = evaluate_baseline_gate(degraded, self.baseline)
                self.assertFalse(result.passed)
                self.assertTrue(any(metric in f for f in result.failures), msg=str(result.failures))

    def test_no_self_derived_baseline_loophole(self) -> None:
        # The loophole: the default/self-derived gating floors (DEFAULT_MIN_METRICS) do NOT include the
        # ranking/faithfulness metrics, so a regression in them goes undetected unless a COMMITTED
        # baseline adds those floors. This proves the committed baseline closes that gap.
        for metric in ("precision_at_k", "mrr", "faithfulness"):
            self.assertNotIn(metric, DEFAULT_MIN_METRICS)
            self.assertIn(metric, self.baseline.min_metrics)

        run = EvaluationRunner(self.sys).run(self.eval_set, principal=self.principal)
        degraded = replace(run, metrics={**run.metrics, "faithfulness": 0.5})

        # A baseline carrying only the DEFAULT-style floors (recall/citation/groundedness) MISSES it.
        weak = EvaluationBaseline(
            metrics={},
            min_metrics={
                k: v for k, v in self.baseline.min_metrics.items() if k in DEFAULT_MIN_METRICS
            },
        )
        self.assertTrue(evaluate_baseline_gate(degraded, weak).passed)

        # The committed baseline (faithfulness floored) CATCHES it.
        committed_result = evaluate_baseline_gate(degraded, self.baseline)
        self.assertFalse(committed_result.passed)
        self.assertTrue(any("faithfulness" in f for f in committed_result.failures))


if __name__ == "__main__":
    unittest.main()
