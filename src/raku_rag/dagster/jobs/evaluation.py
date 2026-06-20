"""T059 - Dagster-compatible scheduled evaluation job boundary."""

from __future__ import annotations

from dataclasses import dataclass, field

from raku_rag.domain.models import IdentityClaims
from raku_rag.eval.models import EvaluationRun, EvaluationSet
from raku_rag.eval.runner import EvaluationRunner


@dataclass(frozen=True)
class EvaluationJobRequest:
    eval_set_id: str
    tenant_id: str
    baseline: bool = False
    collection_id: str = ""
    dagster_tags: dict[str, str] = field(default_factory=dict)


def build_evaluation_job_request(
    eval_set: EvaluationSet,
    *,
    baseline: bool = False,
    collection_id: str = "",
) -> EvaluationJobRequest:
    return EvaluationJobRequest(
        eval_set_id=eval_set.eval_set_id,
        tenant_id=eval_set.tenant_id,
        baseline=baseline,
        collection_id=collection_id,
        dagster_tags={
            "tenant_id": eval_set.tenant_id,
            "eval_set_id": eval_set.eval_set_id,
            "job_type": "evaluation",
        },
    )


def execute_evaluation_job(
    runner: EvaluationRunner,
    eval_set: EvaluationSet,
    *,
    principal: IdentityClaims,
    collection_id: str = "",
    baseline: bool = False,
    security_check_counts: dict[str, int] | None = None,
) -> EvaluationRun:
    return runner.run(
        eval_set,
        principal=principal,
        collection_id=collection_id or None,
        baseline=baseline,
        security_check_counts=security_check_counts,
    )
