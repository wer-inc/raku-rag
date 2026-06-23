"""Evaluation runner package."""

from raku_rag.eval.baseline import (
    EvaluationBaseline,
    EvaluationGateResult,
    baseline_from_run,
    evaluate_baseline_gate,
)
from raku_rag.eval.models import EvaluationItem, EvaluationRun, EvaluationSet, ExpectedEvidence
from raku_rag.eval.probes import ProbeResult, SecurityProbeSuite, SuiteOutcome
from raku_rag.eval.runner import EvaluationRunner
from raku_rag.eval.synthetic_qa import (
    SyntheticQAItem,
    SyntheticQAReviewStatus,
    approve_synthetic_qa_item,
    generate_synthetic_qa_candidates,
    materialize_approved_eval_set,
    reject_synthetic_qa_item,
)
from raku_rag.eval.version_registry import EvaluationVersionRegistry, build_version_registry

__all__ = [
    "EvaluationBaseline",
    "EvaluationGateResult",
    "EvaluationItem",
    "ExpectedEvidence",
    "EvaluationRun",
    "EvaluationSet",
    "EvaluationRunner",
    "EvaluationVersionRegistry",
    "ProbeResult",
    "SecurityProbeSuite",
    "SuiteOutcome",
    "SyntheticQAItem",
    "SyntheticQAReviewStatus",
    "approve_synthetic_qa_item",
    "baseline_from_run",
    "build_version_registry",
    "evaluate_baseline_gate",
    "generate_synthetic_qa_candidates",
    "materialize_approved_eval_set",
    "reject_synthetic_qa_item",
]
