"""T031/T031b — AnswerService (FR-012/013/014/034, US1).

Invariants:
- LLM context = retrieved AND authorized chunks only (RetrievalService already pre-filtered).
- Only chunks that actually support the answer are cited (FR-012).
- Every answer returns used_chunks (constraint) and freshness (FR-005b).
- Insufficient evidence → no guessing (FR-014). Budget exhausted → budget_exceeded (FR-034).
"""

from __future__ import annotations

import time
from dataclasses import replace
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
from raku_rag.observability.audit import AuditEvent, AuditSink
from raku_rag.observability.logging import log, new_correlation_id
from raku_rag.observability.metrics import MetricsRecorder
from raku_rag.observability.tracing import InMemoryTracer
from raku_rag.services.cost import CostService
from raku_rag.services.groundedness import GroundednessGate
from raku_rag.services.injection import PromptInjectionGuard
from raku_rag.services.retrieval import RetrievalService
from raku_rag.services.structured_query import classify_structured_query

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
        audit: AuditSink | None = None,
        vlm: VLMProvider | None = None,
        injection_guard: PromptInjectionGuard | None = None,
        output_guardrail: object | None = None,
        structured_tool: object | None = None,
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
        # P1-2: prompt-injection defense runs in the live flow (default-on, provider-agnostic).
        self._injection_guard = injection_guard or PromptInjectionGuard()
        self._output_guardrail = output_guardrail
        self._structured_tool = structured_tool

    def answer(
        self,
        principal: IdentityClaims,
        query: str,
        profile: QueryProfile,
        collection_id: str | None = None,
    ) -> Answer:
        cid = new_correlation_id()
        total_started = time.perf_counter()
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
            route = classify_structured_query(
                query, tool_available=self._structured_tool is not None
            )
            if route.route == "structured_tool":
                ans = self._answer_with_structured_tool(
                    principal,
                    query,
                    profile,
                    span,
                    cid,
                    total_started,
                    route.reason,
                    collection_id,
                )
                if ans is not None:
                    return ans
            if route.requires_tool:
                status = AnswerStatus.TEMPORARILY_UNAVAILABLE.value
                self._record_metric(principal.tenant_id, profile.profile_id, status, 0)
                self._record_audit(principal, cid, "answer", status, reason=route.reason)
                self._record_hot_path(principal, cid, profile, status, total_started=total_started)
                if hasattr(span, "finish"):
                    span.finish("ok", answer_status=status, route=route.route, reason=route.reason)
                return Answer(status=status, used_chunks=(), correlation_id=cid, route=route.route)

            # Budget gate first (FR-034). Never weakens ACL/groundedness.
            if self._cost.would_exceed(principal.tenant_id, _EST_QUERY_COST):
                log("answer.budget_exceeded", correlation_id=cid, tenant=principal.tenant_id)
                self._record_metric(
                    principal.tenant_id, profile.profile_id, AnswerStatus.BUDGET_EXCEEDED.value, 0
                )
                self._record_audit(
                    principal, cid, "answer", AnswerStatus.BUDGET_EXCEEDED.value, reason="budget"
                )
                self._record_hot_path(
                    principal,
                    cid,
                    profile,
                    AnswerStatus.BUDGET_EXCEEDED.value,
                    total_started=total_started,
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
                self._record_hot_path(
                    principal,
                    cid,
                    profile,
                    status,
                    total_started=total_started,
                )
                if hasattr(span, "finish"):
                    span.finish("ok", answer_status=status)
                return Answer(status=status, used_chunks=(), correlation_id=cid)

            evidence = self._cap_evidence(list(pre.evidence), profile)
            if len(evidence) < profile.minimum_evidence_count:
                log("answer.insufficient_context_budget", correlation_id=cid)
                status = AnswerStatus.INSUFFICIENT_EVIDENCE.value
                self._record_metric(principal.tenant_id, profile.profile_id, status, 0)
                self._record_audit(principal, cid, "answer", status, reason="context_budget")
                context_tokens = self._evidence_token_count(evidence)
                self._record_hot_path(
                    principal,
                    cid,
                    profile,
                    status,
                    total_started=total_started,
                    context_tokens=context_tokens,
                    prompt_tokens=_token_count(query) + context_tokens,
                )
                if hasattr(span, "finish"):
                    span.finish("ok", answer_status=status, reason="context_budget")
                return Answer(status=status, used_chunks=(), correlation_id=cid)

            evidence = self._revalidate_evidence(principal, evidence, cid, profile)
            if len(evidence) < profile.minimum_evidence_count:
                log("answer.insufficient_citation_revalidation", correlation_id=cid)
                status = AnswerStatus.INSUFFICIENT_EVIDENCE.value
                self._record_metric(principal.tenant_id, profile.profile_id, status, 0)
                self._record_audit(principal, cid, "answer", status, reason="citation_revalidation")
                context_tokens = self._evidence_token_count(evidence)
                self._record_hot_path(
                    principal,
                    cid,
                    profile,
                    status,
                    total_started=total_started,
                    context_tokens=context_tokens,
                    prompt_tokens=_token_count(query) + context_tokens,
                )
                if hasattr(span, "finish"):
                    span.finish("ok", answer_status=status, reason="citation_revalidation")
                return Answer(status=status, used_chunks=(), correlation_id=cid)

            # P1-2 prompt-injection defense (defense-in-depth; never widens ACL/groundedness). Both
            # the user query and the retrieved context are untrusted. A query that tries to override
            # the system is REFUSED; instructions embedded in retrieved chunks are NEUTRALIZED before
            # they reach the model (treated as inert data, never obeyed).
            query_injection = self._injection_guard.inspect(query)
            if query_injection.detected:
                log("answer.prompt_injection_query", correlation_id=cid)
                status = AnswerStatus.INSUFFICIENT_EVIDENCE.value
                self._record_metric(principal.tenant_id, profile.profile_id, status, 0)
                self._record_audit(principal, cid, "answer", status, reason="prompt_injection")
                self._record_hot_path(principal, cid, profile, status, total_started=total_started)
                if hasattr(span, "finish"):
                    span.finish("ok", answer_status=status, reason="prompt_injection")
                return Answer(status=status, used_chunks=(), correlation_id=cid)

            context_injection = 0
            context: list[Chunk] = []
            for s in evidence:
                sanitized, neutralized = self._injection_guard.neutralize(s.chunk.text)
                context_injection += neutralized
                context.append(replace(s.chunk, text=sanitized) if neutralized else s.chunk)
            if context_injection:
                # The injected instruction is neutralized, not obeyed; the answer stays grounded in
                # the legitimate content. Recorded so the event is not a silent pass (cf. P1-8) — at
                # PARITY with the query-injection path: log + audit sink + metric (PR-002 hardening),
                # not log-only.
                log(
                    "answer.prompt_injection_context_neutralized",
                    correlation_id=cid,
                    count=context_injection,
                )
                self._record_audit(
                    principal,
                    cid,
                    "answer",
                    "prompt_injection_context_neutralized",
                    reason="prompt_injection_context",
                )
                if self._metrics:
                    self._metrics.increment(
                        "prompt_injection_context_neutralized_total",
                        labels={
                            "tenant_id": principal.tenant_id,
                            "profile_id": profile.profile_id,
                        },
                    )
            context_tokens = sum(_token_count(c.text) for c in context)
            prompt_tokens = _token_count(query) + context_tokens
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
                generation_ms = (time.perf_counter() - generation_started) * 1000
                if self._metrics:
                    self._metrics.record_stage(
                        "generation",
                        tenant_id=principal.tenant_id,
                        status="llm_unavailable",
                        latency_ms=generation_ms,
                    )
                log("answer.llm_unavailable", correlation_id=cid)
                self._record_metric(principal.tenant_id, profile.profile_id, "llm_unavailable", 0)
                self._record_audit(principal, cid, "answer", "failed", reason="llm_unavailable")
                self._record_hot_path(
                    principal,
                    cid,
                    profile,
                    "llm_unavailable",
                    total_started=total_started,
                    llm_call_count=1,
                    generation_ms=generation_ms,
                    context_tokens=context_tokens,
                    prompt_tokens=prompt_tokens,
                )
                raise ProviderUnavailable("LLM provider failed") from exc
            generation_ms = (time.perf_counter() - generation_started) * 1000
            completion_tokens = _token_count(text)
            if self._metrics:
                self._metrics.record_stage(
                    "generation",
                    tenant_id=principal.tenant_id,
                    status="ok",
                    latency_ms=generation_ms,
                )

            self._cost.record_tokens(
                principal.tenant_id,
                kind="llm_prompt_tokens",
                tokens=prompt_tokens,
                trace_id=cid,
                query_id=profile.profile_id,
                metadata={"model": getattr(self._llm, "model", "")},
            )
            self._cost.record_tokens(
                principal.tenant_id,
                kind="llm_completion_tokens",
                tokens=completion_tokens,
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
                self._record_hot_path(
                    principal,
                    cid,
                    profile,
                    status,
                    total_started=total_started,
                    llm_call_count=1,
                    generation_ms=generation_ms,
                    context_tokens=context_tokens,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                )
                if hasattr(span, "finish"):
                    span.finish("ok", answer_status=status)
                return Answer(status=status, used_chunks=(), correlation_id=cid)

            if self._output_guardrail is not None:
                try:
                    verdict = self._output_guardrail.check(text)
                    blocked = bool(getattr(verdict, "blocked", False))
                    reason = str(getattr(verdict, "reason", "") or "output_guardrail")
                except Exception:
                    blocked = True
                    reason = "output_guardrail_unavailable"
                if blocked:
                    status = AnswerStatus.TEMPORARILY_UNAVAILABLE.value
                    log("answer.output_guardrail_blocked", correlation_id=cid, reason=reason)
                    self._record_metric(principal.tenant_id, profile.profile_id, status, 0)
                    self._record_audit(principal, cid, "answer", status, reason=reason)
                    self._record_hot_path(
                        principal,
                        cid,
                        profile,
                        status,
                        total_started=total_started,
                        llm_call_count=1,
                        generation_ms=generation_ms,
                        context_tokens=context_tokens,
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                    )
                    if hasattr(span, "finish"):
                        span.finish("ok", answer_status=status, reason=reason)
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
                if not self._citation_still_visible(principal, c, doc):
                    self._record_citation_revalidation_drop(principal, cid, profile, c)
                    continue
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

            if len(used) < profile.minimum_evidence_count:
                log("answer.insufficient_citation_revalidation", correlation_id=cid)
                status = AnswerStatus.INSUFFICIENT_EVIDENCE.value
                self._record_metric(principal.tenant_id, profile.profile_id, status, len(used))
                self._record_audit(
                    principal,
                    cid,
                    "answer",
                    status,
                    reason="citation_revalidation",
                    document_ids=tuple(c.document_id for c in citations),
                    chunk_ids=tuple(used),
                )
                self._record_hot_path(
                    principal,
                    cid,
                    profile,
                    status,
                    total_started=total_started,
                    llm_call_count=1,
                    generation_ms=generation_ms,
                    context_tokens=context_tokens,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                )
                if hasattr(span, "finish"):
                    span.finish("ok", answer_status=status, reason="citation_revalidation")
                return Answer(status=status, used_chunks=tuple(used), correlation_id=cid)

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
            self._record_hot_path(
                principal,
                cid,
                profile,
                AnswerStatus.OK.value,
                total_started=total_started,
                llm_call_count=1,
                generation_ms=generation_ms,
                context_tokens=context_tokens,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
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
                route="rag",
            )

    def _answer_with_structured_tool(
        self,
        principal: IdentityClaims,
        query: str,
        profile: QueryProfile,
        span,
        correlation_id: str,
        total_started: float,
        reason: str,
        collection_id: str | None,
    ) -> Answer | None:
        if self._structured_tool is None or not hasattr(self._structured_tool, "answer"):
            return None
        try:
            ans = self._structured_tool.answer(
                principal=principal,
                query=query,
                collection_id=collection_id,
                reason=reason,
                correlation_id=correlation_id,
            )
        except Exception:
            status = AnswerStatus.TEMPORARILY_UNAVAILABLE.value
            self._record_metric(principal.tenant_id, profile.profile_id, status, 0)
            self._record_audit(
                principal,
                correlation_id,
                "answer",
                status,
                reason="structured_tool_unavailable",
            )
            self._record_hot_path(
                principal, correlation_id, profile, status, total_started=total_started
            )
            if hasattr(span, "finish"):
                span.finish("ok", answer_status=status, route="structured_tool")
            return Answer(
                status=status,
                used_chunks=(),
                correlation_id=correlation_id,
                route="structured_tool",
            )
        self._record_metric(
            principal.tenant_id, profile.profile_id, ans.status, len(ans.used_chunks)
        )
        self._record_audit(
            principal,
            correlation_id,
            "answer",
            ans.status,
            reason=reason,
            document_ids=tuple(c.document_id for c in ans.citations),
            chunk_ids=ans.used_chunks,
        )
        self._record_hot_path(
            principal,
            correlation_id,
            profile,
            ans.status,
            total_started=total_started,
            context_tokens=0,
            prompt_tokens=_token_count(query),
            completion_tokens=_token_count(ans.text or ""),
        )
        if hasattr(span, "finish"):
            span.finish("ok", answer_status=ans.status, route="structured_tool", reason=reason)
        return ans

    def _revalidate_evidence(
        self,
        principal: IdentityClaims,
        evidence: Sequence[ScoredChunk],
        correlation_id: str,
        profile: QueryProfile,
    ) -> list[ScoredChunk]:
        visible: list[ScoredChunk] = []
        for item in evidence:
            chunk = item.chunk
            doc = self._get_document(chunk.tenant_id, chunk.document_id)
            if self._citation_still_visible(principal, chunk, doc):
                visible.append(item)
                continue
            self._record_citation_revalidation_drop(principal, correlation_id, profile, chunk)
        return visible

    def _citation_still_visible(
        self, principal: IdentityClaims, chunk: Chunk, doc: Document | None
    ) -> bool:
        if doc is None:
            return False
        if doc.tenant_id != principal.tenant_id:
            return False
        if doc.document_id != chunk.document_id:
            return False
        if doc.tombstone:
            return False
        if chunk.tombstone:
            return False
        is_visible = getattr(self._retrieval, "is_visible", None)
        if callable(is_visible):
            return bool(is_visible(principal, chunk))
        return True

    def _record_citation_revalidation_drop(
        self,
        principal: IdentityClaims,
        correlation_id: str,
        profile: QueryProfile,
        chunk: Chunk,
    ) -> None:
        log(
            "answer.citation_revalidation_dropped",
            correlation_id=correlation_id,
            tenant=principal.tenant_id,
            document_id=chunk.document_id,
            chunk_id=chunk.chunk_id,
        )
        if self._metrics:
            self._metrics.increment(
                "answer_citation_revalidation_dropped_total",
                labels={
                    "tenant_id": principal.tenant_id,
                    "profile_id": profile.profile_id,
                },
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

    def _cap_evidence(
        self, evidence: Sequence[ScoredChunk], profile: QueryProfile
    ) -> list[ScoredChunk]:
        chunk_limit = max(0, int(profile.max_context_chunks))
        token_limit = max(0, int(profile.max_context_tokens))
        if chunk_limit == 0 or token_limit == 0:
            return []
        capped: list[ScoredChunk] = []
        used_tokens = 0
        for item in evidence:
            if len(capped) >= chunk_limit:
                break
            chunk_tokens = _token_count(item.chunk.text)
            if chunk_tokens <= 0:
                chunk_tokens = item.chunk.token_count if item.chunk.token_count > 0 else 0
            if used_tokens + chunk_tokens > token_limit:
                continue
            capped.append(item)
            used_tokens += chunk_tokens
        return capped

    def _evidence_token_count(self, evidence: Sequence[ScoredChunk]) -> int:
        return sum(_token_count(item.chunk.text) for item in evidence)

    def _record_hot_path(
        self,
        principal: IdentityClaims,
        correlation_id: str,
        profile: QueryProfile,
        status: str,
        *,
        total_started: float,
        llm_call_count: int = 0,
        generation_ms: float = 0.0,
        context_tokens: int = 0,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        cache_hit: bool = False,
    ) -> None:
        if not self._metrics:
            return
        attrs = self._retrieval_span_attrs(correlation_id)
        total_ms = (time.perf_counter() - total_started) * 1000
        self._metrics.record_rag_hot_path(
            request_id=correlation_id,
            tenant_id=principal.tenant_id,
            user_id=principal.user_id,
            profile_id=profile.profile_id,
            status=status,
            llm_call_count=llm_call_count,
            retrieval_ms=self._float_attr(attrs, "retrieval_ms"),
            rerank_ms=self._float_attr(attrs, "rerank_ms"),
            generation_ms=generation_ms,
            total_ms=total_ms,
            retrieved_chunks=self._int_attr(attrs, "retrieved_chunks"),
            rerank_input_count=self._int_attr(attrs, "rerank_input_count"),
            context_tokens=context_tokens,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cache_hit=cache_hit,
        )

    def _retrieval_span_attrs(self, correlation_id: str) -> dict:
        if not self._tracer:
            return {}
        for span in self._tracer.spans(correlation_id=correlation_id):
            if span.name == "retrieval.retrieve":
                return dict(span.attributes)
        return {}

    def _float_attr(self, attrs: dict, key: str) -> float:
        try:
            return float(attrs.get(key) or 0.0)
        except (TypeError, ValueError):
            return 0.0

    def _int_attr(self, attrs: dict, key: str) -> int:
        try:
            return int(attrs.get(key) or 0)
        except (TypeError, ValueError):
            return 0

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
