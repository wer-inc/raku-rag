"""T026 — RetrievalService: ACL pre-filter retrieval + double-defense post-check (FR-022).

The ACL/tenant/tombstone filter is enforced inside VectorStore.search as a PRE-filter. This service
additionally re-asserts visibility on every returned chunk (fail-closed) and applies rerank.
"""
from __future__ import annotations

from raku_rag.core.security.acl import AclPolicy
from raku_rag.domain.models import IdentityClaims, QueryProfile, ScoredChunk
from raku_rag.interfaces.base import EmbeddingProvider, Reranker, VectorStore


class RetrievalService:
    def __init__(
        self,
        store: VectorStore,
        embedder: EmbeddingProvider,
        acl: AclPolicy,
        reranker: Reranker | None = None,
    ) -> None:
        self._store = store
        self._embedder = embedder
        self._acl = acl
        self._reranker = reranker

    def retrieve(
        self, principal: IdentityClaims, query: str, profile: QueryProfile
    ) -> list[ScoredChunk]:
        query_vec = self._embedder.embed([query])[0]
        visible = self._acl.visibility(principal)
        # PRE-filter happens inside search (tenant + tombstone + ACL).
        scored = self._store.search(
            principal.tenant_id, query_vec, visible=visible, top_k=max(profile.top_k, profile.rerank_top_n)
        )
        # Double defense: re-assert ACL on every result (fail-closed if anything slipped through).
        for s in scored:
            self._acl.assert_visible(principal, s.chunk)
        if profile.rerank_enabled and self._reranker is not None:
            try:
                scored = self._reranker.rerank(query, scored, profile.rerank_top_n)
            except Exception:
                pass  # fail-safe: fall back to un-reranked (FR-030); gate decides if usable
        return scored[: profile.top_k]
