"""T044 — DeletionService (FR-008, SC-003): tombstone immediately, cascade + invalidate cache.

Orchestrates: mark document tombstone → exclude from retrieval immediately → invalidate caches →
purge chunks (inline here; async in production). A deleted document must never reappear in
search/answer/citation (SC-003).
"""
from __future__ import annotations

from dataclasses import dataclass

from raku_rag.interfaces.base import VectorStore
from raku_rag.services.cache import CacheService
from raku_rag.services.ingestion import DocumentRegistry


@dataclass
class DeletionResult:
    tombstoned_chunks: int
    invalidated_cache_entries: int
    purged_chunks: int


class DeletionService:
    def __init__(
        self, store: VectorStore, registry: DocumentRegistry, cache: CacheService
    ) -> None:
        self._store = store
        self._registry = registry
        self._cache = cache

    def delete(self, tenant_id: str, document_id: str) -> DeletionResult:
        # 1) immediate tombstone (document + chunks) → excluded from retrieval at once
        doc = self._registry.get(tenant_id, document_id)
        if doc:
            doc.tombstone = True
        tombstoned = self._store.set_tombstone(tenant_id, document_id, True)
        # 2) invalidate any cached retrieval/answer depending on this document
        invalidated = self._cache.invalidate_document(tenant_id, document_id)
        # 3) cascade physical purge (async in production; inline here)
        purged = self._store.purge(tenant_id, document_id)
        return DeletionResult(tombstoned, invalidated, purged)
