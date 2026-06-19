"""T031/T031b — AnswerService (FR-012/013/014/034, US1).

Invariants:
- LLM context = retrieved AND authorized chunks only (RetrievalService already pre-filtered).
- Only chunks that actually support the answer are cited (FR-012).
- Every answer returns used_chunks (constraint) and freshness (FR-005b).
- Insufficient evidence → no guessing (FR-014). Budget exhausted → budget_exceeded (FR-034).
"""
from __future__ import annotations

from typing import Callable, Sequence

from raku_rag.core.errors import AnswerStatus, ProviderUnavailable
from raku_rag.core.text import content_terms as _terms
from raku_rag.domain.models import (
    Answer,
    Chunk,
    Citation,
    Document,
    Freshness,
    IdentityClaims,
    QueryProfile,
    ScoredChunk,
)
from raku_rag.interfaces.base import LLMProvider
from raku_rag.observability.logging import log, new_correlation_id
from raku_rag.services.cost import CostService
from raku_rag.services.groundedness import GroundednessGate
from raku_rag.services.retrieval import RetrievalService

_EST_QUERY_COST = 1.0

GetDocument = Callable[[str, str], Document | None]  # (tenant_id, document_id) -> Document


class AnswerService:
    def __init__(
        self,
        retrieval: RetrievalService,
        llm: LLMProvider,
        gate: GroundednessGate,
        cost: CostService,
        get_document: GetDocument,
    ) -> None:
        self._retrieval = retrieval
        self._llm = llm
        self._gate = gate
        self._cost = cost
        self._get_document = get_document

    def answer(
        self, principal: IdentityClaims, query: str, profile: QueryProfile
    ) -> Answer:
        cid = new_correlation_id()

        # Budget gate first (FR-034). Never weakens ACL/groundedness.
        if self._cost.would_exceed(principal.tenant_id, _EST_QUERY_COST):
            log("answer.budget_exceeded", correlation_id=cid, tenant=principal.tenant_id)
            return Answer(status=AnswerStatus.BUDGET_EXCEEDED.value, used_chunks=(), correlation_id=cid)

        scored = self._retrieval.retrieve(principal, query, profile)

        pre = self._gate.pre_gate(scored, profile)
        if not pre.passed:
            log("answer.insufficient", correlation_id=cid, reason=pre.reason)
            return Answer(
                status=AnswerStatus.INSUFFICIENT_EVIDENCE.value, used_chunks=(), correlation_id=cid
            )

        evidence: list[ScoredChunk] = list(pre.evidence)
        context: Sequence[Chunk] = [s.chunk for s in evidence]

        try:
            text = self._llm.generate(query, context)
        except Exception as exc:  # fail-closed (FR-030)
            log("answer.llm_unavailable", correlation_id=cid)
            raise ProviderUnavailable("LLM provider failed") from exc

        post = self._gate.post_check(text, context)
        if not post.passed:
            log("answer.insufficient_postcheck", correlation_id=cid, reason=post.reason)
            return Answer(
                status=AnswerStatus.INSUFFICIENT_EVIDENCE.value, used_chunks=(), correlation_id=cid
            )

        ans_terms = _terms(text)
        citations: list[Citation] = []
        used: list[str] = []
        freshness: list[Freshness] = []
        for s in evidence:
            c = s.chunk
            if not (ans_terms & _terms(c.text)):
                continue  # cite only chunks that actually support the answer (FR-012)
            doc = self._get_document(c.tenant_id, c.document_id)
            citations.append(
                Citation(
                    kind="text",
                    document_id=c.document_id,
                    source_id=doc.source_id if doc else "",
                    version=doc.version if doc else 0,
                    retrieval_score=s.retrieval_score,
                    chunk_id=c.chunk_id,
                    text_range=(0, len(c.text)),
                )
            )
            used.append(c.chunk_id)
            if doc:
                freshness.append(
                    Freshness(indexed_at=doc.indexed_at, document_version=doc.version)
                )

        cost = self._cost.record(principal.tenant_id, _EST_QUERY_COST, kind="answer")
        confidence = max((s.retrieval_score for s in evidence), default=0.0)
        log("answer.ok", correlation_id=cid, used=len(used))
        return Answer(
            status=AnswerStatus.OK.value,
            text=text,
            confidence=confidence,
            citations=tuple(citations),
            used_chunks=tuple(used),
            used_modalities=("text",),
            freshness=tuple(freshness),
            cost=cost,
            correlation_id=cid,
        )
