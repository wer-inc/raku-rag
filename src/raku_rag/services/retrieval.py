"""T026 - RetrievalService: ACL pre-filter retrieval + double-defense post-check (FR-022).

The ACL/tenant/tombstone filter is enforced inside VectorStore.search as a PRE-filter. This service
additionally re-asserts visibility on every returned chunk (fail-closed) and applies rerank.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Mapping

from raku_rag.core.query_planner import plan_query
from raku_rag.core.security.acl import AclPolicy
from raku_rag.domain.models import Chunk, IdentityClaims, QueryProfile, ScoredChunk
from raku_rag.interfaces.base import EmbeddingProvider, Reranker, VectorStore
from raku_rag.observability.logging import log
from raku_rag.observability.metrics import MetricsRecorder
from raku_rag.observability.tracing import InMemoryTracer
from raku_rag.services.cache import CacheService
from raku_rag.services.cost import CostService

MAX_RERANK_CANDIDATES = 80
QUERY_PLAN_DOCUMENT_KIND_BOOST = 0.06
QUERY_PLAN_SAFETY_SCOPE_BOOST = 0.06
QUERY_PLAN_IDENTIFIER_BOOST = 0.02


def _token_count(text: str) -> int:
    return len(text.split())


def _rerank_candidate_limit(profile: QueryProfile) -> int:
    return max(0, min(int(profile.rerank_top_n), MAX_RERANK_CANDIDATES))


def _embedder_cache_identity(embedder: EmbeddingProvider) -> str:
    """Stable identity for the embedding model so cached vectors never cross model versions.

    Mirrors eval/version_registry.py: prefer the provider ``capability`` (provider + model_version +
    dimensions), fall back to the ``model_version`` attribute (e.g. ``hashing-bow-v2`` — the same
    identity stamped on chunks at ingest), then to the class name so an unidentified provider still
    gets a non-empty, type-scoped key.
    """
    capability = getattr(embedder, "capability", None)
    provider = str(getattr(capability, "provider", "") or "")
    model_version = str(
        getattr(capability, "model_version", "")
        or getattr(embedder, "model_version", "")
        or type(embedder).__name__
    )
    dims = (
        getattr(capability, "dimensions", None)
        or getattr(embedder, "dim", None)
        or getattr(embedder, "dimensions", None)
        or 0
    )
    return f"{provider}:{model_version}:{dims}"


def _merge_hybrid_results(*result_sets: list[ScoredChunk]) -> list[ScoredChunk]:
    """Union hybrid retrieval legs without duplicating chunks."""
    merged_by_id: dict[str, ScoredChunk] = {}
    order: list[str] = []
    for results in result_sets:
        for scored in results:
            chunk_id = scored.chunk.chunk_id
            if chunk_id not in merged_by_id:
                order.append(chunk_id)
                merged_by_id[chunk_id] = scored
                continue
            if scored.retrieval_score > merged_by_id[chunk_id].retrieval_score:
                merged_by_id[chunk_id] = scored
    return [merged_by_id[chunk_id] for chunk_id in order]


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
        rerank_trace_sink: object | None = None,
        cache: CacheService | None = None,
    ) -> None:
        self._store = store
        self._embedder = embedder
        self._acl = acl
        self._reranker = reranker
        self._cost = cost
        self._metrics = metrics
        self._tracer = tracer
        # ★G1: optional durable sink (rerank_traces table); fail-open, never blocks retrieval.
        self._rerank_trace_sink = rerank_trace_sink
        # ★G5 query-embedding cache (default None = behaviour unchanged). Every request re-embeds
        # the query — with a real embedding provider (OpenAI text-embedding-3) that is a paid API
        # call per request. Keys are tenant-scoped via CacheService's (tenant_id, key) contract and
        # include the embedding model identity so a provider/version swap can never serve vectors
        # from the old model. NOTE: query→vector is content-independent, so these entries need NO
        # document-deletion invalidation (they carry no document_ids); deleted documents are still
        # filtered by the tenant/ACL/tombstone PRE-filter on every search.
        self._cache = cache
        self._embed_cache_identity = _embedder_cache_identity(embedder) if cache else ""

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
            query_plan = plan_query(query)
            rerank_candidate_limit = _rerank_candidate_limit(profile)
            search_top_k = max(1, profile.top_k, rerank_candidate_limit)
            metric_labels = {"tenant_id": principal.tenant_id, "profile_id": profile.profile_id}
            query_vec, embed_cache_hit = self._embed_query(
                principal.tenant_id, query, metric_labels, correlation_id
            )
            if self._cost and not embed_cache_hit:
                # A cache hit skips the embedding call entirely, so no embedding cost is incurred
                # (or recorded) for it — that saving is the point of the cache.
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
            metadata_exact_matches: list[ScoredChunk] = []
            exact_matcher = getattr(self._store, "metadata_exact_matches", None)
            if callable(exact_matcher):
                metadata_exact_matches = exact_matcher(
                    principal.tenant_id,
                    query,
                    visible=visible,
                    top_k=search_top_k,
                )
            lexical_matches: list[ScoredChunk] = []
            lexical_matcher = getattr(self._store, "lexical_matches", None)
            if callable(lexical_matcher):
                lexical_matches = lexical_matcher(
                    principal.tenant_id,
                    query,
                    visible=visible,
                    top_k=search_top_k,
                )
            if metadata_exact_matches or lexical_matches:
                scored = _merge_hybrid_results(metadata_exact_matches, lexical_matches, scored)
            scored = _apply_query_plan_boosts(scored, query_plan)
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

            if self._rerank_trace_sink is not None and rerank_status != "skipped":
                try:
                    self._rerank_trace_sink.record(
                        tenant_id=principal.tenant_id,
                        query_id=correlation_id,
                        retrieval_profile_id=profile.profile_id,
                        provider=type(self._reranker).__name__,
                        model=getattr(self._reranker, "model", ""),
                        candidate_count=rerank_input_count,
                        final_context_count=len(result),
                        latency_ms=rerank_ms,
                    )
                except Exception:
                    if self._metrics:
                        self._metrics.increment(
                            "rerank_trace_persist_failures_total", labels=metric_labels
                        )

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
                self._metrics.observe(
                    "retrieval_metadata_exact_match_count",
                    len(metadata_exact_matches),
                    labels=metric_labels,
                )
                self._metrics.observe(
                    "retrieval_lexical_match_count",
                    len(lexical_matches),
                    labels=metric_labels,
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
                    metadata_exact_match_count=len(metadata_exact_matches),
                    lexical_match_count=len(lexical_matches),
                    retrieval_outcome=outcome,
                    prefiltered_count=(prefiltered_count if prefiltered_count is not None else -1),
                    query_intent=query_plan.intent,
                    query_identifier_count=len(query_plan.identifiers),
                    query_lexical_term_count=len(query_plan.lexical_terms),
                    query_rewrite_hint_count=len(query_plan.rewrite_hints),
                    query_filter_hints=sorted(query_plan.filter_hints),
                    embed_cache_hit=embed_cache_hit,
                )
            if self._metrics:
                self._metrics.record_stage(
                    "retrieval",
                    tenant_id=principal.tenant_id,
                    status="ok",
                    latency_ms=(time.perf_counter() - started) * 1000,
                )
            return result

    def _embed_query(
        self,
        tenant_id: str,
        query: str,
        metric_labels: dict[str, str],
        correlation_id: str,
    ) -> tuple[list[float], bool]:
        """Embed the query, serving repeats from the tenant-scoped embedding cache (★G5).

        Cache key = ("embed", embedding model identity, sha256(query)); the tenant scope comes from
        CacheService's (tenant_id, key) contract. Every cache interaction is fail-open: a cache
        error is logged/metered and the query is embedded as if no cache were configured.
        """
        if self._cache is None:
            return self._embedder.embed([query])[0], False
        key = (
            "embed:"
            f"{self._embed_cache_identity}:"
            f"{hashlib.sha256(query.encode('utf-8')).hexdigest()}"
        )
        try:
            cached = self._cache.get(tenant_id, key)
        except Exception as exc:  # fail-open: cache errors never break retrieval
            cached = None
            log(
                "retrieval.embed_cache_error",
                correlation_id=correlation_id,
                tenant=tenant_id,
                op="get",
                error=type(exc).__name__,
            )
            if self._metrics:
                self._metrics.increment("embedding_cache_errors_total", labels=metric_labels)
        if isinstance(cached, tuple):
            if self._metrics:
                self._metrics.increment("embedding_cache_hits_total", labels=metric_labels)
            return list(cached), True
        query_vec = self._embedder.embed([query])[0]
        if self._metrics:
            self._metrics.increment("embedding_cache_misses_total", labels=metric_labels)
        try:
            # Stored as an immutable tuple so later callers can't mutate the cached vector.
            # document_ids is empty on purpose: a query embedding depends on no document content,
            # so document deletion must NOT invalidate it (see the constructor note).
            self._cache.put(tenant_id, key, tuple(query_vec), set())
        except Exception as exc:  # fail-open
            log(
                "retrieval.embed_cache_error",
                correlation_id=correlation_id,
                tenant=tenant_id,
                op="put",
                error=type(exc).__name__,
            )
            if self._metrics:
                self._metrics.increment("embedding_cache_errors_total", labels=metric_labels)
        return query_vec, False

    def is_visible(self, principal: IdentityClaims, chunk: Chunk) -> bool:
        """Re-check current ACL/tenant/tombstone visibility for already-retrieved evidence.

        Retrieval applies this before scoring, but citation rendering is a second channel. This
        method lets answer/draft surfaces fail closed if a document is tombstoned or ACL-revoked
        after retrieval but before the response is served.
        """
        if chunk.tenant_id != principal.tenant_id:
            return False
        if getattr(chunk, "tombstone", False):
            return False
        try:
            self._acl.assert_visible(principal, chunk)
        except Exception:
            return False
        return True


def _apply_query_plan_boosts(scored: list[ScoredChunk], query_plan) -> list[ScoredChunk]:
    if not scored or query_plan.intent == "clarification":
        return scored
    boosted: list[ScoredChunk] = []
    for item in scored:
        boost = _query_plan_boost(item.chunk, query_plan)
        boosted.append(ScoredChunk(item.chunk, item.retrieval_score + boost))
    return sorted(boosted, key=lambda item: item.retrieval_score, reverse=True)


def _query_plan_boost(chunk: Chunk, query_plan) -> float:
    boost = 0.0
    kinds = query_plan.filter_hints.get("document_kind") or ()
    if kinds and _metadata_has_any(chunk.metadata, "document_kind", kinds):
        boost += QUERY_PLAN_DOCUMENT_KIND_BOOST
    if query_plan.filter_hints.get("safety_scope") and _metadata_has_any(
        chunk.metadata, "safety_category", ("high_risk",)
    ):
        boost += QUERY_PLAN_SAFETY_SCOPE_BOOST
    if query_plan.identifiers and _metadata_has_identifier(chunk.metadata, query_plan.identifiers):
        boost += QUERY_PLAN_IDENTIFIER_BOOST
    return boost


def _metadata_has_any(metadata: Mapping[str, object], key: str, accepted: tuple[str, ...]) -> bool:
    accepted_values = {str(value).strip().casefold() for value in accepted if str(value).strip()}
    if not accepted_values:
        return False
    for value in _metadata_values(metadata, key):
        if str(value).strip().casefold() in accepted_values:
            return True
    return False


def _metadata_has_identifier(metadata: Mapping[str, object], identifiers: tuple[str, ...]) -> bool:
    identifier_values = {str(value).replace("-", "").casefold() for value in identifiers}
    for key in ("equipment_id", "alarm_code"):
        for value in _metadata_values(metadata, key):
            normalized = str(value).replace("-", "").casefold()
            if normalized and normalized in identifier_values:
                return True
    return False


def _metadata_values(metadata: object, key: str) -> tuple[object, ...]:
    mapping = _as_mapping(metadata)
    if mapping is None:
        return ()
    values: list[object] = []
    value = mapping.get(key)
    if isinstance(value, (list, tuple)):
        values.extend(value)
    elif value not in (None, ""):
        values.append(value)
    extra = mapping.get("extra")
    if isinstance(extra, Mapping):
        values.extend(_metadata_values(extra, key))
    for nested_key in ("_mfg_meta", "manufacturing", "manufacturing_metadata", "industry_metadata"):
        child = mapping.get(nested_key)
        if child is not metadata:
            values.extend(_metadata_values(child, key))
    return tuple(values)


def _as_mapping(value: object) -> Mapping[str, object] | None:
    if isinstance(value, Mapping):
        return value
    to_mapping = getattr(value, "to_mapping", None)
    if callable(to_mapping):
        mapped = to_mapping()
        return mapped if isinstance(mapped, Mapping) else None
    return None


class _NullSpan:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def finish(self, *args, **kwargs) -> None:
        return None


def _null_span() -> _NullSpan:
    return _NullSpan()
