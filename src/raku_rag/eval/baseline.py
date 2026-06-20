"""T085 - evaluation baseline regression gates."""

from __future__ import annotations

from dataclasses import dataclass, field

from raku_rag.eval.models import EvaluationRun


@dataclass(frozen=True)
class EvaluationBaseline:
    metrics: dict[str, float]
    min_metrics: dict[str, float] = field(default_factory=dict)
    max_metrics: dict[str, float] = field(default_factory=dict)
    security_checks: tuple[str, ...] = ()


@dataclass(frozen=True)
class EvaluationGateResult:
    passed: bool
    failures: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {"passed": self.passed, "failures": list(self.failures)}


DEFAULT_MIN_METRICS: dict[str, float] = {
    "recall_at_k": 1.0,
    "citation_accuracy": 1.0,
    "groundedness": 1.0,
    "visual_recall_at_k": 1.0,
    "visual_citation_accuracy": 1.0,
    "bbox_iou": 0.95,
    "visual_groundedness": 1.0,
}

DEFAULT_MAX_METRICS: dict[str, float] = {
    "p95_latency_ms": 2_000.0,
    "p95_visual_answer_latency_ms": 5_000.0,
    "query_cost": 100.0,
    "visual_query_cost": 100.0,
}


def baseline_from_run(run: EvaluationRun) -> EvaluationBaseline:
    return EvaluationBaseline(
        metrics={key: float(value) for key, value in run.metrics.items()},
        min_metrics=dict(DEFAULT_MIN_METRICS),
        max_metrics=dict(DEFAULT_MAX_METRICS),
        security_checks=tuple(run.security_checks.keys()),
    )


def evaluate_baseline_gate(
    run: EvaluationRun,
    baseline: EvaluationBaseline,
    *,
    min_metrics: dict[str, float] | None = None,
    max_metrics: dict[str, float] | None = None,
) -> EvaluationGateResult:
    minima = {**baseline.min_metrics, **(min_metrics or {})}
    maxima = {**baseline.max_metrics, **(max_metrics or {})}
    failures: list[str] = []
    for key, threshold in minima.items():
        value = float(run.metrics.get(key, 0.0))
        if value < threshold:
            failures.append(f"{key}={value} below {threshold}")
    for key, threshold in maxima.items():
        value = float(run.metrics.get(key, 0.0))
        if value > threshold:
            failures.append(f"{key}={value} above {threshold}")
    for key in baseline.security_checks:
        check = run.security_checks.get(key, {})
        if check and not check.get("passed", False):
            failures.append(f"security check failed: {key}")
    if run.gate_result != "passed":
        failures.append(f"gate_result={run.gate_result}")
    return EvaluationGateResult(passed=not failures, failures=tuple(failures))


__all__ = [
    "DEFAULT_MAX_METRICS",
    "DEFAULT_MIN_METRICS",
    "EvaluationBaseline",
    "EvaluationGateResult",
    "baseline_from_run",
    "evaluate_baseline_gate",
]
