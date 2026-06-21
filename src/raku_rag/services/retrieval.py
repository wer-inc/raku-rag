"""T026 - RetrievalService: ACL pre-filter retrieval + double-defense post-check (FR-022).

The ACL/tenant/tombstone filter is enforced inside VectorStore.search as a PRE-filter. This service
additionally re-asserts visibility on every returned chunk (fail-closed) and applies rerank.
"""

from __future__ import annotations

import time

from raku_rag.core.security.acl import AclPolicy
from raku_rag.domain.models import IdentityClaims, QueryProfile, ScoredChunk
from raku_rag.interfaces.base import EmbeddingProvider, Reranker, VectorStore
from raku_rag.observability.metrics import MetricsRecorder
from raku_rag.observability.tracing import InMemoryTracer
from raku_rag.services.cost import CostService


MAX_RERANK_CANDIDATES = 80


def _token_count(text: str) -> int:
    return len(text.split())


def _rerank_candidate_limit(profile: QueryProfile) -> int:
    return max(0, min(int(profile.rerank_top_n), MAX_RERANK_CANDIDATES))


class RetrievalService:
    def __init__(
        self,
        store: VectorStore,
        embedder: EmbeddingProvider,
        acl: AclPolicy,
        reranker: Reranker | None = None,
        cost: CostService | None = None,
        metrics: MetricsRecorder | None = None,
        tracer: InMemoryTracer | None = None,
    ) -> None:
        self._store = store
        self._embedder = embedder
        self._acl = acl
        self._reranker = reranker
        self._cost = cost
        self._metrics = metrics
        self._tracer = tracer

    def retrieve(
        self,
        principal: IdentityClaims,
        query: str,
        profile: QueryProfile,
        *,
        correlation_id: str = "",
    ) -> list[ScoredChunk]:
        started = time.perf_counter()
        span_cm = (
            self._tracer.span(
                "retrieval.retrieve",
                correlation_id=correlation_id,
                tenant_id=principal.tenant_id,
                profile_id=profile.profile_id,
            )
            if self._tracer
            else _null_span()
        )
        with span_cm as span:
            rerank_candidate_limit = _rerank_candidate_limit(profile)
            search_top_k = max(1, profile.top_k, rerank_candidate_limit)
            query_vec = self._embedder.embed([query])[0]
            if self._cost:
                self._cost.record_tokens(
                    principal.tenant_id,
                    kind="embedding_tokens",
                    tokens=_token_count(query),
                    trace_id=correlation_id,
                    query_id=profile.profile_id,
                    metadata={"target": "query"},
                )
            visible = self._acl.visibility(principal)
            # PRE-filter happens inside search (tenant + tombstone + ACL).
            scored = self._store.search(
                principal.tenant_id,
                query_vec,
                visible=visible,
                top_k=search_top_k,
            )
            # Double defense: re-assert ACL on every result (fail-closed if anything slipped through).
            for s in scored:
                self._acl.assert_visible(principal, s.chunk)
            retrieval_ms = (time.perf_counter() - started) * 1000
            rerank_ms = 0.0
            rerank_input_count = 0
            if profile.rerank_enabled and self._reranker is not None and rerank_candidate_limit > 0:
                rerank_input = scored[:rerank_candidate_limit]
                rerank_input_count = len(rerank_input)
                rerank_started = time.perf_counter()
                try:
                    scored = self._reranker.rerank(query, rerank_input, rerank_candidate_limit)
                except Exception:
                    scored = rerank_input  # fail-safe: fall back to capped un-reranked results.
                rerank_ms = (time.perf_counter() - rerank_started) * 1000
            result = scored[: profile.top_k]
            if self._metrics:
                metric_labels = {"tenant_id": principal.tenant_id, "profile_id": profile.profile_id}
                self._metrics.increment("retrieval_requests_total", labels=metric_labels)
                self._metrics.observe("retrieval_result_count", len(result), labels=metric_labels)
                self._metrics.observe("retrieval_rerank_input_count", rerank_input_count, labels=metric_labels)
                self._metrics.observe("retrieval_rerank_ms", rerank_ms, labels=metric_labels)
            if hasattr(span, "finish"):
                span.finish(
                    "ok",
                    result_count=len(result),
                    retrieved_chunks=len(result),
                    rerank_input_count=rerank_input_count,
                    retrieval_ms=retrieval_ms,
                    rerank_ms=rerank_ms,
                )
            if self._metrics:
                self._metrics.record_stage(
                    "retrieval",
                    tenant_id=principal.tenant_id,
                    status="ok",
                    latency_ms=(time.perf_counter() - started) * 1000,
                )
            return result


class _NullSpan:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def finish(self, *args, **kwargs) -> None:
        return None


def _null_span() -> _NullSpan:
    return _NullSpan()
