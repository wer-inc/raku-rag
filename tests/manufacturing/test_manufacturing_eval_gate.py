from __future__ import annotations

from dataclasses import replace
import unittest

from raku_rag.eval.models import EvaluationRun
from raku_rag.manufacturing.kpi.poc_metrics import (
    PocKpiReport,
    attach_manufacturing_kpis_to_evaluation_run,
)


class ManufacturingEvaluationGateTest(unittest.TestCase):
    def test_evaluation_run_gets_manufacturing_kpis_and_baseline_comparison(self) -> None:
        run = EvaluationRun(
            run_id="eval_1",
            eval_set_id="set_1",
            tenant_id="tenant_mfg",
            status="succeeded",
            metrics={"recall_at_k": 1.0},
        )
        report = PocKpiReport(
            self_resolution_rate=0.9,
            grounded_answer_rate=0.8,
            high_risk_query_count=3,
            safety_gate_block_count=1,
            materialized_at="2026-06-20T00:00:00+00:00",
        )
        baseline = replace(
            run,
            metrics={
                "manufacturing_self_resolution_rate": 0.8,
                "manufacturing_grounded_answer_rate": 0.75,
            },
        )

        enriched = attach_manufacturing_kpis_to_evaluation_run(
            run,
            report,
            baseline_run=baseline,
            safety_check_counts={
                "manufacturing_high_risk_approved_citation_requirement": 0,
            },
        )

        self.assertEqual(enriched.metrics["manufacturing_self_resolution_rate"], 0.9)
        self.assertEqual(enriched.metrics["manufacturing_high_risk_query_count"], 3)
        self.assertAlmostEqual(
            enriched.baseline_comparison["manufacturing_self_resolution_rate"],
            0.1,
        )
        self.assertEqual(enriched.gate_result, "passed")

    def test_absolute_manufacturing_safety_gate_blocks_regardless_of_baseline(self) -> None:
        run = EvaluationRun(
            run_id="eval_1",
            eval_set_id="set_1",
            tenant_id="tenant_mfg",
            status="succeeded",
            metrics={},
        )
        enriched = attach_manufacturing_kpis_to_evaluation_run(
            run,
            PocKpiReport(),
            safety_check_counts={
                "manufacturing_high_risk_approved_citation_requirement": 1,
            },
        )

        self.assertEqual(enriched.gate_result, "blocked")
        self.assertFalse(
            enriched.security_checks["manufacturing_high_risk_approved_citation_requirement"][
                "passed"
            ]
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
