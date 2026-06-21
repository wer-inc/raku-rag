"""T026 - RetrievalService: ACL pre-filter retrieval + double-defense post-check (FR-022).

The ACL/tenant/tombstone filter is enforced inside VectorStore.search as a PRE-filter. This service
additionally re-asserts visibility on every returned chunk (fail-closed) and applies rerank.
"""

from __future__ import annotations

import time

from raku_rag.core.security.acl import AclPolicy
from raku_rag.domain.models import IdentityClaims, QueryProfile, ScoredChunk
from raku_rag.interfaces.base import EmbeddingProvider, Reranker, VectorStore
from raku_rag.observability.logging import log
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
            # P1-8: the count of candidates that PASSED the tenant/ACL/tombstone pre-filter. Exported
            # so an empty retrieval is attributable (nothing visible vs a post-filter bug), not silent.
            prefiltered_count = getattr(self._store, "last_prefiltered_count", None)
            retrieval_ms = (time.perf_counter() - started) * 1000
            rerank_ms = 0.0
            rerank_input_count = 0
            rerank_status = "skipped"
            rerank_error = ""
            metric_labels = {"tenant_id": principal.tenant_id, "profile_id": profile.profile_id}
            if profile.rerank_enabled and self._reranker is not None and rerank_candidate_limit > 0:
                rerank_input = scored[:rerank_candidate_limit]
                rerank_input_count = len(rerank_input)
                rerank_started = time.perf_counter()
                try:
                    scored = self._reranker.rerank(query, rerank_input, rerank_candidate_limit)
                    rerank_status = "ok"
                except Exception as exc:
                    # Rerank stays fail-safe (fall back to capped order) but the failure is NOT silent:
                    # it is logged, metered, and recorded on the span so degraded ranking is visible.
                    scored = rerank_input
                    rerank_status = "failed"
                    rerank_error = type(exc).__name__
                    log(
                        "retrieval.rerank_failed",
                        correlation_id=correlation_id,
                        tenant=principal.tenant_id,
                        error=rerank_error,
                    )
                    if self._metrics:
                        self._metrics.increment(
                            "retrieval_rerank_failures_total", labels=metric_labels
                        )
                rerank_ms = (time.perf_counter() - rerank_started) * 1000
            result = scored[: profile.top_k]

            # P1-8 root-cause attribution for an empty retrieval (PR-006): never a silent zero.
            if result:
                outcome = "ok"
            elif prefiltered_count and prefiltered_count > 0:
                outcome = "post_filter_empty"  # candidates passed the pre-filter but none survived
            else:
                outcome = "no_visible_candidates"  # no match, or tenant/ACL/tombstone removed all
            if not result:
                log(
                    "retrieval.empty",
                    correlation_id=correlation_id,
                    tenant=principal.tenant_id,
                    outcome=outcome,
                    prefiltered_count=prefiltered_count,
                )
            if self._metrics:
                self._metrics.increment("retrieval_requests_total", labels=metric_labels)
                self._metrics.observe("retrieval_result_count", len(result), labels=metric_labels)
                self._metrics.observe(
                    "retrieval_rerank_input_count", rerank_input_count, labels=metric_labels
                )
                self._metrics.observe("retrieval_rerank_ms", rerank_ms, labels=metric_labels)
                if prefiltered_count is not None:
                    self._metrics.observe(
                        "retrieval_prefiltered_count",
                        float(prefiltered_count),
                        labels=metric_labels,
                    )
                if not result:
                    self._metrics.increment(
                        "retrieval_empty_total", labels={**metric_labels, "outcome": outcome}
                    )
            if hasattr(span, "finish"):
                span.finish(
                    "ok",
                    result_count=len(result),
                    retrieved_chunks=len(result),
                    rerank_input_count=rerank_input_count,
                    retrieval_ms=retrieval_ms,
                    rerank_ms=rerank_ms,
                    rerank_status=rerank_status,
                    rerank_error=rerank_error,
                    retrieval_outcome=outcome,
                    prefiltered_count=(prefiltered_count if prefiltered_count is not None else -1),
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
