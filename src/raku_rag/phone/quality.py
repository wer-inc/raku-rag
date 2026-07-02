"""T071/T072 — Phone QA evaluation workflow (022 US4).

Supervisors review completed calls (correctness / tone / handoff appropriateness / compliance /
hallucination / privacy) and improvement-worthy findings flow into the SAME audit-derived
knowledge-improvement queue the rest of the product uses (`manufacturing/api/improvements.py`) —
no parallel feedback store; the audit log stays the single source of truth (reference IDs only,
never review free text).
"""

from __future__ import annotations

from typing import Protocol

from raku_rag.domain.models import IdentityClaims
from raku_rag.phone.domain import QualityEvaluation, new_id

QA_REVIEW_ROLES = frozenset({"qa_reviewer", "ops_owner", "tenant_admin"})

_SCORE_FIELDS = ("answer_correctness", "tone_score", "handoff_appropriateness")


class QualityRepository(Protocol):
    def save(self, evaluation: QualityEvaluation) -> None: ...

    def list_for_call(self, tenant_id: str, call_id: str) -> list[QualityEvaluation]: ...

    def list_all(self, tenant_id: str) -> list[QualityEvaluation]: ...


def evaluation_public(evaluation: QualityEvaluation) -> dict:
    return {
        "evaluation_id": evaluation.evaluation_id,
        "call_id": evaluation.call_id,
        "reviewer_id": evaluation.reviewer_id,
        "reviewed_at": evaluation.reviewed_at,
        "answer_correctness": evaluation.answer_correctness,
        "tone_score": evaluation.tone_score,
        "handoff_appropriateness": evaluation.handoff_appropriateness,
        "compliance_issue": evaluation.compliance_issue,
        "hallucination_detected": evaluation.hallucination_detected,
        "privacy_issue": evaluation.privacy_issue,
        "suggested_fix": evaluation.suggested_fix,
        "knowledge_gap_topics": list(evaluation.knowledge_gap_topics),
        "review_status": evaluation.review_status,
        "improvement_item_id": evaluation.improvement_item_id,
    }


class PhoneQualityService:
    """Validates and persists QA reviews; bridges flagged findings into the improvement queue."""

    def __init__(self, repository: QualityRepository, audit=None) -> None:
        self._repo = repository
        self._audit = audit

    def can_review(self, principal: IdentityClaims) -> bool:
        return bool(set(principal.roles) & QA_REVIEW_ROLES)

    def create_evaluation(
        self, principal: IdentityClaims, call_id: str, body: dict
    ) -> tuple[int, dict, QualityEvaluation | None]:
        if not self.can_review(principal):
            return 403, {"error": "forbidden"}, None

        scores: dict[str, int | None] = {}
        for field in _SCORE_FIELDS:
            value = body.get(field)
            if value is None or value == "":
                scores[field] = None
                continue
            try:
                score = int(value)
            except (TypeError, ValueError):
                return 422, {"error": "invalid_score", "field": field}, None
            if not 1 <= score <= 5:
                return 422, {"error": "invalid_score", "field": field}, None
            scores[field] = score

        hallucination = bool(body.get("hallucination_detected"))
        topics = [str(t).strip() for t in body.get("knowledge_gap_topics") or [] if str(t).strip()]
        suggested_fix = str(body.get("suggested_fix") or "").strip() or None
        if hallucination and not (suggested_fix or topics):
            # Data-model invariant: a hallucination flag must carry an actionable follow-up.
            return 422, {"error": "hallucination_requires_fix_or_topics"}, None

        knowledge_gap = bool(topics)
        improvement_item_id = new_id("imp") if (hallucination or knowledge_gap) else None
        evaluation = QualityEvaluation(
            tenant_id=principal.tenant_id,
            evaluation_id=new_id("eval"),
            call_id=call_id,
            reviewer_id=principal.user_id,
            answer_correctness=scores["answer_correctness"],
            tone_score=scores["tone_score"],
            handoff_appropriateness=scores["handoff_appropriateness"],
            compliance_issue=bool(body.get("compliance_issue")),
            hallucination_detected=hallucination,
            privacy_issue=bool(body.get("privacy_issue")),
            suggested_fix=suggested_fix,
            knowledge_gap_topics=topics,
            improvement_item_id=improvement_item_id,
        )
        self._repo.save(evaluation)

        if self._audit is not None:
            from raku_rag.manufacturing.api.audit import record_phone_quality_evaluation

            record_phone_quality_evaluation(
                self._audit,
                tenant_id=principal.tenant_id,
                actor_id=principal.user_id,
                call_id=call_id,
                evaluation_id=evaluation.evaluation_id,
                hallucination_detected=hallucination,
                knowledge_gap=knowledge_gap,
                compliance_issue=evaluation.compliance_issue,
                privacy_issue=evaluation.privacy_issue,
                improvement_item_id=improvement_item_id,
            )
        return 201, evaluation_public(evaluation), evaluation

    def list_for_call(self, principal: IdentityClaims, call_id: str) -> tuple[int, dict]:
        if not self.can_review(principal):
            return 403, {"error": "forbidden"}
        evaluations = self._repo.list_for_call(principal.tenant_id, call_id)
        return 200, {"items": [evaluation_public(e) for e in evaluations]}
