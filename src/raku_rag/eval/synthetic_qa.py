"""Deterministic synthetic QA candidates with SME approval gating.

Synthetic questions are useful for coverage, but they must not silently become release gates. This
module keeps generated candidates separate from `EvaluationItem`; only SME-approved candidates can be
materialized into an `EvaluationSet`.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Iterable, Mapping

from raku_rag.core.text import content_terms
from raku_rag.domain.models import Chunk
from raku_rag.eval.models import EvaluationSet, ExpectedEvidence
from raku_rag.observability.redaction import Redactor


class SyntheticQAReviewStatus(str, Enum):
    GENERATED = "generated"
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass(frozen=True)
class SyntheticQAItem:
    question: str
    expected_answer: str
    expected_evidence: tuple[ExpectedEvidence, ...]
    source_document_id: str
    source_chunk_id: str
    review_status: SyntheticQAReviewStatus = SyntheticQAReviewStatus.GENERATED
    reviewer_id: str = ""
    review_note: str = ""
    generator_version: str = "synthetic_qa_deterministic_v1"

    def to_mapping(self) -> dict:
        return {
            "question": self.question,
            "expected_answer": self.expected_answer,
            "expected_evidence": [e.__dict__ for e in self.expected_evidence],
            "source_document_id": self.source_document_id,
            "source_chunk_id": self.source_chunk_id,
            "review_status": self.review_status.value,
            "reviewer_id": self.reviewer_id,
            "review_note": self.review_note,
            "generator_version": self.generator_version,
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, object]) -> "SyntheticQAItem":
        evidence = []
        for item in data.get("expected_evidence") or ():
            raw = dict(item)
            evidence.append(
                ExpectedEvidence(
                    document_id=str(raw.get("document_id") or ""),
                    chunk_id=str(raw.get("chunk_id") or ""),
                    kind=str(raw.get("kind") or "text"),
                    asset_id=str(raw.get("asset_id") or ""),
                    region_id=str(raw.get("region_id") or ""),
                )
            )
        return cls(
            question=str(data.get("question") or ""),
            expected_answer=str(data.get("expected_answer") or ""),
            expected_evidence=tuple(evidence),
            source_document_id=str(data.get("source_document_id") or ""),
            source_chunk_id=str(data.get("source_chunk_id") or ""),
            review_status=SyntheticQAReviewStatus(
                str(data.get("review_status") or SyntheticQAReviewStatus.GENERATED.value)
            ),
            reviewer_id=str(data.get("reviewer_id") or ""),
            review_note=str(data.get("review_note") or ""),
            generator_version=str(data.get("generator_version") or "synthetic_qa_deterministic_v1"),
        )

    def to_eval_mapping(self) -> dict:
        if self.review_status != SyntheticQAReviewStatus.APPROVED:
            raise ValueError("synthetic QA item must be SME-approved before it can gate eval")
        return {
            "question": self.question,
            "expected_answer": self.expected_answer,
            "expected_evidence": [e.__dict__ for e in self.expected_evidence],
        }


def generate_synthetic_qa_candidates(
    chunks: Iterable[Chunk], *, limit: int | None = None, redactor: Redactor | None = None
) -> tuple[SyntheticQAItem, ...]:
    redactor = redactor or Redactor()
    items: list[SyntheticQAItem] = []
    for chunk in chunks:
        if chunk.tombstone or not chunk.text.strip():
            continue
        answer = _answer_excerpt(chunk.text)
        if not answer:
            continue
        question = _question_for_chunk(chunk)
        items.append(
            SyntheticQAItem(
                question=redactor.redact(question),
                expected_answer=redactor.redact(answer),
                expected_evidence=(
                    ExpectedEvidence(document_id=chunk.document_id, chunk_id=chunk.chunk_id),
                ),
                source_document_id=chunk.document_id,
                source_chunk_id=chunk.chunk_id,
            )
        )
        if limit is not None and len(items) >= limit:
            break
    return tuple(items)


def approve_synthetic_qa_item(
    item: SyntheticQAItem, *, reviewer_id: str, review_note: str = ""
) -> SyntheticQAItem:
    if not reviewer_id.strip():
        raise ValueError("reviewer_id is required to approve a synthetic QA item")
    return replace(
        item,
        review_status=SyntheticQAReviewStatus.APPROVED,
        reviewer_id=reviewer_id.strip(),
        review_note=review_note,
    )


def reject_synthetic_qa_item(
    item: SyntheticQAItem, *, reviewer_id: str, review_note: str = ""
) -> SyntheticQAItem:
    if not reviewer_id.strip():
        raise ValueError("reviewer_id is required to reject a synthetic QA item")
    return replace(
        item,
        review_status=SyntheticQAReviewStatus.REJECTED,
        reviewer_id=reviewer_id.strip(),
        review_note=review_note,
    )


def materialize_approved_eval_set(
    *,
    tenant_id: str,
    candidates: Iterable[SyntheticQAItem],
    eval_set_id: str = "",
    redactor: Redactor | None = None,
) -> EvaluationSet:
    approved = [
        item.to_eval_mapping()
        for item in candidates
        if item.review_status == SyntheticQAReviewStatus.APPROVED
    ]
    if not approved:
        raise ValueError("at least one SME-approved synthetic QA item is required")
    return EvaluationSet.register(
        tenant_id=tenant_id,
        items=approved,
        eval_set_id=eval_set_id,
        redactor=redactor,
    )


def _answer_excerpt(text: str) -> str:
    normalized = " ".join(text.split())
    if not normalized:
        return ""
    sentence_end = min(
        [idx + 1 for idx in (normalized.find("."), normalized.find("。")) if idx >= 0]
        or [len(normalized)]
    )
    return normalized[: min(sentence_end, 240)].strip()


def _question_for_chunk(chunk: Chunk) -> str:
    title = chunk.heading_path[-1] if chunk.heading_path else chunk.document_id
    terms = sorted(content_terms(chunk.text))
    topic = " ".join(terms[:4]) if terms else "the cited section"
    return f"What does {title} state about {topic}?"
