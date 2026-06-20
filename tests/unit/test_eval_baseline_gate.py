"""T085 - evaluation baseline regression gate."""

from __future__ import annotations

import unittest
from dataclasses import replace

from raku_rag.eval import EvaluationBaseline, baseline_from_run, evaluate_baseline_gate
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


if __name__ == "__main__":
    unittest.main()
