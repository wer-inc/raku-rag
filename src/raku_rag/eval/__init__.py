"""Evaluation runner package."""

from raku_rag.eval.baseline import (
    EvaluationBaseline,
    EvaluationGateResult,
    baseline_from_run,
    evaluate_baseline_gate,
)
from raku_rag.eval.models import EvaluationItem, EvaluationRun, EvaluationSet, ExpectedEvidence
from raku_rag.eval.runner import EvaluationRunner

__all__ = [
    "EvaluationBaseline",
    "EvaluationGateResult",
    "EvaluationItem",
    "ExpectedEvidence",
    "EvaluationRun",
    "EvaluationSet",
    "EvaluationRunner",
    "baseline_from_run",
    "evaluate_baseline_gate",
]
