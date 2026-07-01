"""T085 - evaluation baseline regression gate."""

from __future__ import annotations

import unittest
from dataclasses import replace

from raku_rag.eval import EvaluationBaseline, baseline_from_run, evaluate_baseline_gate
from raku_rag.eval.baseline import DEFAULT_MIN_METRICS
from tests.fixtures import load_json
from tests.helpers import claims, fresh

T = "tenant_a"


class TestEvalBaselineGate(unittest.TestCase):
    def _visual_run(self):
        from raku_rag.domain.models import ScopeType, SubjectType
        from raku_rag.eval import EvaluationRunner, EvaluationSet

        sys = fresh()
        alice = claims(T, "alice")
        sys.grant(T, ScopeType.COLLECTION, "manuals", SubjectType.USER, "alice")
        result = sys.ingest_visual_fixture(
            tenant_id=T,
            collection_id="manuals",
            document_id="panel_image",
            image=b"OCR: Pump panel shows alarm AL-42.",
        )
        region = result.regions[0]
        eval_set = EvaluationSet.register(
            tenant_id=T,
            items=[
                {
                    "question": "what alarm does the pump panel show?",
                    "expected_answer": "AL-42",
                    "expected_evidence": [
                        {
                            "kind": "visual",
                            "document_id": "panel_image",
                            "asset_id": result.asset.asset_id,
                            "region_id": region.region_id,
                            "bbox": {
                                "x": region.bbox.x,
                                "y": region.bbox.y,
                                "width": region.bbox.width,
                                "height": region.bbox.height,
                            },
                        }
                    ],
                }
            ],
        )
        return EvaluationRunner(sys).run(eval_set, principal=alice, collection_id="manuals")

    def test_baseline_fixture_declares_text_visual_metrics_and_security_checks(self) -> None:
        fixture = load_json("eval", "baseline.json")

        self.assertIn("recall_at_k", fixture["min_metrics"])
        self.assertIn("visual_recall_at_k", fixture["min_metrics"])
        self.assertIn("bbox_iou", fixture["min_metrics"])
        self.assertIn("p95_visual_answer_latency_ms", fixture["max_metrics"])
        self.assertIn("visual_acl_leakage", fixture["security_checks"])

    def test_visual_run_passes_default_baseline_gate(self) -> None:
        run = self._visual_run()
        baseline = baseline_from_run(run)

        gate = evaluate_baseline_gate(run, baseline)

        self.assertTrue(gate.passed, gate.failures)

    def test_metric_or_security_regression_blocks_gate(self) -> None:
        run = self._visual_run()
        baseline = EvaluationBaseline(
            metrics=dict(run.metrics),
            min_metrics={"visual_recall_at_k": 1.0},
            max_metrics={"p95_visual_answer_latency_ms": 5_000.0},
            security_checks=("visual_acl_leakage",),
        )
        regressed = replace(
            run,
            metrics={**run.metrics, "visual_recall_at_k": 0.0},
            security_checks={
                **run.security_checks,
                "visual_acl_leakage": {"passed": False, "count": 1},
            },
            gate_result="blocked",
        )

        gate = evaluate_baseline_gate(regressed, baseline)

        self.assertFalse(gate.passed)
        self.assertTrue(any("visual_recall_at_k" in failure for failure in gate.failures))
        self.assertTrue(any("visual_acl_leakage" in failure for failure in gate.failures))

    def test_claim_groundedness_regression_blocks_gate_that_whole_answer_groundedness_misses(
        self,
    ) -> None:
        """P2 (chatbot-conversational-agent-roadmap): `groundedness` is a whole-answer bag-of-words
        overlap proxy — an answer that shares ONE term with its evidence satisfies it even if it also
        invents an unsupported number/identifier elsewhere (the gap a genuinely generative provider,
        e.g. BedrockClaudeLLMProvider, could hit; today's extractive provider cannot by construction).
        `claim_groundedness` (backed by GroundednessGate.claim_check, eval/runner.py) is the per-claim
        strengthening: seed IT down while leaving `groundedness` at a passing 1.0, and the gate must
        still block — proving the new metric, not the old one, is what catches this class of failure.
        Before this metric existed, a run seeded this way (groundedness=1.0, no security regression)
        would have passed `evaluate_baseline_gate` outright.
        """
        run = self._visual_run()
        baseline = EvaluationBaseline(
            metrics=dict(run.metrics),
            min_metrics={"groundedness": 1.0, "claim_groundedness": 1.0},
        )
        regressed = replace(
            run,
            metrics={**run.metrics, "groundedness": 1.0, "claim_groundedness": 0.0},
        )

        gate = evaluate_baseline_gate(regressed, baseline)

        self.assertFalse(gate.passed)
        self.assertTrue(any("claim_groundedness" in failure for failure in gate.failures))
        # The old whole-answer metric alone would not have flagged this regression (it is not itself
        # a reported failure — `claim_groundedness=...` above deliberately also contains the substring
        # "groundedness=", so this checks for the OLD key exactly, not a substring of the new one).
        self.assertFalse(any(failure.startswith("groundedness=") for failure in gate.failures))

    def test_claim_groundedness_is_a_default_release_blocking_floor(self) -> None:
        # Not just available to opt into per-baseline: baseline_from_run (the self-derived path) must
        # enforce it by default, same as groundedness/citation_accuracy, or a caller that forgets to
        # ask for it would silently lose this coverage.
        self.assertIn("claim_groundedness", DEFAULT_MIN_METRICS)
        self.assertEqual(DEFAULT_MIN_METRICS["claim_groundedness"], 1.0)


if __name__ == "__main__":
    unittest.main()
