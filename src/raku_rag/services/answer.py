"""T031/T031b — AnswerService (FR-012/013/014/034, US1).

Invariants:
- LLM context = retrieved AND authorized chunks only (RetrievalService already pre-filtered).
- Only chunks that actually support the answer are cited (FR-012).
- Every answer returns used_chunks (constraint) and freshness (FR-005b).
- Insufficient evidence → no guessing (FR-014). Budget exhausted → budget_exceeded (FR-034).
"""

from __future__ import annotations

import time
from typing import Callable, Sequence

from raku_rag.core.errors import AnswerStatus, ProviderUnavailable
from raku_rag.core.text import content_terms as _terms
from raku_rag.domain.models import (
    Answer,
    BoundingBox,
    Chunk,
    Citation,
    Document,
    Freshness,
    IdentityClaims,
    LayoutRegion,
    Modality,
    QueryProfile,
    ScoredChunk,
)
from raku_rag.interfaces.base import LLMProvider, VLMProvider
from raku_rag.observability.audit import AuditEvent, InMemoryAuditSink
from raku_rag.observability.logging import log, new_correlation_id
from raku_rag.observability.metrics import MetricsRecorder
from raku_rag.observability.tracing import InMemoryTracer
from raku_rag.services.cost import CostService
from raku_rag.services.groundedness import GroundednessGate
from raku_rag.services.retrieval import RetrievalService

_EST_QUERY_COST = 1.0

GetDocument = Callable[[str, str], Document | None]  # (tenant_id, document_id) -> Document


def _token_count(text: str) -> int:
    return len(text.split())


class AnswerService:
    def __init__(
        self,
        retrieval: RetrievalService,
        llm: LLMProvider,
        gate: GroundednessGate,
        cost: CostService,
        get_document: GetDocument,
        metrics: MetricsRecorder | None = None,
        tracer: InMemoryTracer | None = None,
        audit: InMemoryAuditSink | None = None,
        vlm: VLMProvider | None = None,
    ) -> None:
        self._retrieval = retrieval
        self._llm = llm
        self._gate = gate
        self._cost = cost
        self._get_document = get_document
        self._metrics = metrics
        self._tracer = tracer
        self._audit = audit
        self._vlm = vlm

    def answer(self, principal: IdentityClaims, query: str, profile: QueryProfile) -> Answer:
        cid = new_correlation_id()
        span_cm = (
            self._tracer.span(
                "answer.answer",
                correlation_id=cid,
                tenant_id=principal.tenant_id,
                profile_id=profile.profile_id,
            )
            if self._tracer
            else _null_span()
        )

        with span_cm as span:
            # Budget gate first (FR-034). Never weakens ACL/groundedness.
            if self._cost.would_exceed(principal.tenant_id, _EST_QUERY_COST):
                log("answer.budget_exceeded", correlation_id=cid, tenant=principal.tenant_id)
                self._record_metric(
                    principal.tenant_id, profile.profile_id, AnswerStatus.BUDGET_EXCEEDED.value, 0
                )
                self._record_audit(
                    principal, cid, "answer", AnswerStatus.BUDGET_EXCEEDED.value, reason="budget"
                )
                if hasattr(span, "finish"):
                    span.finish("ok", answer_status=AnswerStatus.BUDGET_EXCEEDED.value)
                return Answer(
                    status=AnswerStatus.BUDGET_EXCEEDED.value, used_chunks=(), correlation_id=cid
                )

            scored = self._retrieval.retrieve(principal, query, profile, correlation_id=cid)

            pre = self._gate.pre_gate(scored, profile)
            if not pre.passed:
                log("answer.insufficient", correlation_id=cid, reason=pre.reason)
                status = AnswerStatus.INSUFFICIENT_EVIDENCE.value
                self._record_metric(principal.tenant_id, profile.profile_id, status, 0)
                self._record_audit(principal, cid, "answer", status, reason=pre.reason)
                if hasattr(span, "finish"):
                    span.finish("ok", answer_status=status)
                return Answer(status=status, used_chunks=(), correlation_id=cid)

            evidence: list[ScoredChunk] = list(pre.evidence)
            context: Sequence[Chunk] = [s.chunk for s in evidence]
            visual_regions = tuple(
                self._layout_region_from_chunk(c) for c in context if c.modality == Modality.VISUAL
            )
            use_vlm = bool(visual_regions) and self._vlm is not None

            generation_started = time.perf_counter()
            generation_cm = (
                self._tracer.span(
                    "generation.generate",
                    correlation_id=cid,
                    tenant_id=principal.tenant_id,
                    profile_id=profile.profile_id,
                    model=getattr(self._vlm if use_vlm else self._llm, "model", ""),
                    modality="visual" if use_vlm else "text",
                )
                if self._tracer
                else _null_span()
            )
            try:
                with generation_cm as generation_span:
                    if use_vlm and self._vlm is not None:
                        text = self._vlm.generate(query, visual_regions=visual_regions)
                    else:
                        text = self._llm.generate(query, context)
                    if hasattr(generation_span, "finish"):
                        generation_span.finish(
                            "ok",
                            context_chunks=len(context),
                            visual_regions=len(visual_regions),
                        )
            except Exception as exc:  # fail-closed (FR-030)
                if self._metrics:
                    self._metrics.record_stage(
                        "generation",
                        tenant_id=principal.tenant_id,
                        status="llm_unavailable",
                        latency_ms=(time.perf_counter() - generation_started) * 1000,
                    )
                log("answer.llm_unavailable", correlation_id=cid)
                self._record_metric(principal.tenant_id, profile.profile_id, "llm_unavailable", 0)
                self._record_audit(principal, cid, "answer", "failed", reason="llm_unavailable")
                raise ProviderUnavailable("LLM provider failed") from exc
            if self._metrics:
                self._metrics.record_stage(
                    "generation",
                    tenant_id=principal.tenant_id,
                    status="ok",
                    latency_ms=(time.perf_counter() - generation_started) * 1000,
                )

            self._cost.record_tokens(
                principal.tenant_id,
                kind="llm_prompt_tokens",
                tokens=_token_count(query) + sum(_token_count(c.text) for c in context),
                trace_id=cid,
                query_id=profile.profile_id,
                metadata={"model": getattr(self._llm, "model", "")},
            )
            self._cost.record_tokens(
                principal.tenant_id,
                kind="llm_completion_tokens",
                tokens=_token_count(text),
                trace_id=cid,
                query_id=profile.profile_id,
                metadata={"model": getattr(self._llm, "model", "")},
            )
            if use_vlm:
                self._cost.record_visual_cost(
                    principal.tenant_id,
                    kind="vlm_image_tokens",
                    amount=0.0,
                    trace_id=cid,
                    query_id=profile.profile_id,
                    quantity=_token_count(query)
                    + sum(_token_count(region.ocr_text) for region in visual_regions),
                    unit="tokens",
                    billable=False,
                    metadata={"model": getattr(self._vlm, "model", "")},
                )

            post = self._gate.post_check(text, context)
            if not post.passed:
                log("answer.insufficient_postcheck", correlation_id=cid, reason=post.reason)
                status = AnswerStatus.INSUFFICIENT_EVIDENCE.value
                self._record_metric(principal.tenant_id, profile.profile_id, status, 0)
                self._record_audit(principal, cid, "answer", status, reason=post.reason)
                if hasattr(span, "finish"):
                    span.finish("ok", answer_status=status)
                return Answer(status=status, used_chunks=(), correlation_id=cid)

            ans_terms = _terms(text)
            citations: list[Citation] = []
            used: list[str] = []
            freshness: list[Freshness] = []
            for s in evidence:
                c = s.chunk
                if not (ans_terms & _terms(c.text)):
                    continue  # cite only chunks that actually support the answer (FR-012)
                doc = self._get_document(c.tenant_id, c.document_id)
                is_visual = c.modality == Modality.VISUAL
                citations.append(
                    Citation(
                        kind="visual" if is_visual else "text",
                        document_id=c.document_id,
                        source_id=doc.source_id if doc else "",
                        version=doc.version if doc else 0,
                        retrieval_score=s.retrieval_score,
                        chunk_id=c.chunk_id,
                        text_range=(0, len(c.text)) if not is_visual else None,
                        asset_id=str(c.metadata.get("asset_id", "")) if is_visual else "",
                        page_number=int(c.metadata.get("page_number") or 0) if is_visual else 0,
                        region_id=str(c.metadata.get("region_id", "")) if is_visual else "",
                        bbox=self._bbox_from_metadata(c) if is_visual else None,
                        crop_uri=str(c.metadata.get("crop_uri", "")) if is_visual else "",
                    )
                )
                used.append(c.chunk_id)
                if doc:
                    freshness.append(
                        Freshness(indexed_at=doc.indexed_at, document_version=doc.version)
                    )

            cost = self._cost.record(
                principal.tenant_id, _EST_QUERY_COST, kind="answer", trace_id=cid
            )
            confidence = max((s.retrieval_score for s in evidence), default=0.0)
            log("answer.ok", correlation_id=cid, used=len(used))
            self._record_metric(
                principal.tenant_id, profile.profile_id, AnswerStatus.OK.value, len(used)
            )
            self._record_audit(
                principal,
                cid,
                "answer",
                AnswerStatus.OK.value,
                document_ids=tuple(c.document_id for c in citations),
                chunk_ids=tuple(used),
            )
            if hasattr(span, "finish"):
                span.finish("ok", answer_status=AnswerStatus.OK.value, used_chunks=len(used))
            return Answer(
                status=AnswerStatus.OK.value,
                text=text,
                confidence=confidence,
                citations=tuple(citations),
                used_chunks=tuple(used),
                used_modalities=self._used_modalities(evidence, tuple(used)),
                freshness=tuple(freshness),
                cost=cost,
                correlation_id=cid,
            )

    def _layout_region_from_chunk(self, chunk: Chunk) -> LayoutRegion:
        bbox = self._bbox_from_metadata(chunk) or BoundingBox(0.0, 0.0, 1.0, 1.0)
        return LayoutRegion(
            tenant_id=chunk.tenant_id,
            collection_id=chunk.collection_id,
            document_id=chunk.document_id,
            asset_id=str(chunk.metadata.get("asset_id", "")),
            region_id=str(chunk.metadata.get("region_id", chunk.chunk_id)),
            bbox=bbox,
            page_number=int(chunk.metadata.get("page_number") or 1),
            region_type=str(chunk.metadata.get("region_type", "text")),
            heading_path=chunk.heading_path,
            ocr_text=str(
                chunk.metadata.get("primary_evidence_text") or chunk.metadata.get("ocr_text") or ""
            ),
            generated_caption_text=str(chunk.metadata.get("generated_caption_text") or ""),
            crop_uri=str(chunk.metadata.get("crop_uri") or ""),
            metadata=dict(chunk.metadata),
            tombstone=chunk.tombstone,
        )

    def _bbox_from_metadata(self, chunk: Chunk) -> BoundingBox | None:
        raw = chunk.metadata.get("bbox")
        if isinstance(raw, BoundingBox):
            return raw
        if isinstance(raw, dict):
            return BoundingBox(
                x=float(raw.get("x", 0.0)),
                y=float(raw.get("y", 0.0)),
                width=float(raw.get("width", 0.0)),
                height=float(raw.get("height", 0.0)),
            )
        return None

    def _used_modalities(
        self, evidence: Sequence[ScoredChunk], used_chunks: tuple[str, ...]
    ) -> tuple[str, ...]:
        used_set = set(used_chunks)
        modalities: list[str] = []
        for item in evidence:
            if item.chunk.chunk_id not in used_set:
                continue
            value = (
                item.chunk.modality.value
                if isinstance(item.chunk.modality, Modality)
                else str(item.chunk.modality)
            )
            if value not in modalities:
                modalities.append(value)
        return tuple(modalities) or ("text",)

    def _record_metric(
        self, tenant_id: str, profile_id: str, status: str, used_chunks: int
    ) -> None:
        if not self._metrics:
            return
        self._metrics.increment(
            "answer_requests_total",
            labels={"tenant_id": tenant_id, "profile_id": profile_id, "status": status},
        )
        self._metrics.observe(
            "answer_used_chunks",
            used_chunks,
            labels={"tenant_id": tenant_id, "profile_id": profile_id, "status": status},
        )

    def _record_audit(
        self,
        principal: IdentityClaims,
        correlation_id: str,
        action: str,
        decision: str,
        *,
        reason: str = "",
        document_ids: tuple[str, ...] = (),
        chunk_ids: tuple[str, ...] = (),
    ) -> None:
        if not self._audit:
            return
        self._audit.record(
            AuditEvent(
                tenant_id=principal.tenant_id,
                correlation_id=correlation_id,
                action=action,
                decision=decision,
                actor_id=principal.user_id,
                resource_type="query",
                document_ids=document_ids,
                chunk_ids=chunk_ids,
                reason=reason,
            )
        )


class _NullSpan:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def finish(self, *args, **kwargs) -> None:
        return None


def _null_span() -> _NullSpan:
    return _NullSpan()
