"""T026 — RetrievalService: ACL pre-filter retrieval + double-defense post-check (FR-022).

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


def _token_count(text: str) -> int:
    return len(text.split())


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
                top_k=max(profile.top_k, profile.rerank_top_n),
            )
            # Double defense: re-assert ACL on every result (fail-closed if anything slipped through).
            for s in scored:
                self._acl.assert_visible(principal, s.chunk)
            if profile.rerank_enabled and self._reranker is not None:
                try:
                    scored = self._reranker.rerank(query, scored, profile.rerank_top_n)
                except Exception:
                    pass  # fail-safe: fall back to un-reranked (FR-030); gate decides if usable
            result = scored[: profile.top_k]
            if self._metrics:
                self._metrics.increment(
                    "retrieval_requests_total",
                    labels={"tenant_id": principal.tenant_id, "profile_id": profile.profile_id},
                )
                self._metrics.observe(
                    "retrieval_result_count",
                    len(result),
                    labels={"tenant_id": principal.tenant_id, "profile_id": profile.profile_id},
                )
            if hasattr(span, "finish"):
                span.finish("ok", result_count=len(result))
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
