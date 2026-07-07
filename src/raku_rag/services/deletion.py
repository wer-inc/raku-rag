"""T044 — DeletionService (FR-008, SC-003): tombstone immediately, cascade + invalidate cache.

Orchestrates: mark document tombstone → exclude from retrieval immediately → invalidate caches →
purge chunks (inline here; async in production). A deleted document must never reappear in
search/answer/citation (SC-003).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from raku_rag.interfaces.base import VectorStore
from raku_rag.services.cache import CacheService
from raku_rag.services.ingestion import DocumentRegistry
from raku_rag.services.ingestion_quality import purge_quality_partitioned_document


@dataclass
class DeletionResult:
    tombstoned_chunks: int
    invalidated_cache_entries: int
    purged_chunks: int
    tombstoned_crops: int = 0
    invalidated_visual_cache_entries: int = 0
    tombstoned_visual_assets: int = 0
    tombstoned_visual_regions: int = 0
    tombstoned_visual_embeddings: int = 0


@dataclass(frozen=True)
class DeletionRecord:
    tenant_id: str
    document_id: str
    deleted_at: str
    reason: str = "delete_request"


@dataclass(frozen=True)
class _VisualRefs:
    asset_ids: frozenset[str] = frozenset()
    region_ids: frozenset[str] = frozenset()
    crop_ids: frozenset[str] = frozenset()


class DeletionService:
    def __init__(
        self,
        store: VectorStore,
        registry: DocumentRegistry,
        cache: CacheService,
        deletion_log: list[DeletionRecord] | None = None,
        crop_store: object | None = None,
    ) -> None:
        self._store = store
        self._registry = registry
        self._cache = cache
        self._deletion_log = deletion_log if deletion_log is not None else []
        self._crop_store = crop_store

    def delete(self, tenant_id: str, document_id: str) -> DeletionResult:
        visual_refs = self._visual_refs(tenant_id, document_id)
        # 1) immediate tombstone (document + chunks) → excluded from retrieval at once
        doc = self._registry.get(tenant_id, document_id)
        if doc:
            # Persist the doc-level tombstone. In-memory relied on by-reference mutation, which is a
            # no-op against the Postgres registry — so a later restore (re-ingest with the same
            # checksum) was wrongly skipped by the ingestion idempotency guard and the purged chunks
            # never came back, diverging from the in-memory backend. Writing it back restores parity.
            doc.tombstone = True
            self._registry.put(doc)
        self._record(tenant_id, document_id)
        tombstoned = self._store.set_tombstone(tenant_id, document_id, True)
        # 2) invalidate any cached retrieval/answer depending on this document
        invalidated = self._cache.invalidate_document(tenant_id, document_id)
        invalidated_visual = self._cache.invalidate_visual_artifacts(
            tenant_id,
            asset_ids=set(visual_refs.asset_ids),
            crop_ids=set(visual_refs.crop_ids),
        )
        # 3) derived visual crops inherit deletion/tombstone from the source document
        tombstoned_crops = self._tombstone_crops(tenant_id, document_id)
        # 4) cascade physical purge (async in production; inline here)
        purged = purge_quality_partitioned_document(self._store, tenant_id, document_id)
        return DeletionResult(
            tombstoned,
            invalidated + invalidated_visual,
            purged,
            tombstoned_crops,
            invalidated_visual,
            len(visual_refs.asset_ids),
            len(visual_refs.region_ids),
            len(visual_refs.region_ids),
        )

    def deletion_log(self, tenant_id: str) -> tuple[DeletionRecord, ...]:
        return tuple(record for record in self._deletion_log if record.tenant_id == tenant_id)

    def reapply_tombstones(self, tenant_id: str) -> int:
        """Re-apply deletion records after backup/restore (FR-008a).

        A restore can accidentally bring document/chunk rows back as live. The deletion log is the
        reference list of documents that must remain tombstoned before serving traffic.
        """

        applied = 0
        for record in self.deletion_log(tenant_id):
            visual_refs = self._visual_refs(record.tenant_id, record.document_id)
            doc = self._registry.get(record.tenant_id, record.document_id)
            if doc:
                doc.tombstone = True
                self._registry.put(doc)  # persist on Postgres too (parity with in-memory mutation)
            self._store.set_tombstone(record.tenant_id, record.document_id, True)
            self._cache.invalidate_document(record.tenant_id, record.document_id)
            self._cache.invalidate_visual_artifacts(
                record.tenant_id,
                asset_ids=set(visual_refs.asset_ids),
                crop_ids=set(visual_refs.crop_ids),
            )
            self._tombstone_crops(record.tenant_id, record.document_id)
            applied += 1
        return applied

    def _record(self, tenant_id: str, document_id: str) -> None:
        if any(
            r.tenant_id == tenant_id and r.document_id == document_id for r in self._deletion_log
        ):
            return
        deleted_at = datetime.now(timezone.utc).isoformat()
        self._deletion_log.append(
            DeletionRecord(tenant_id=tenant_id, document_id=document_id, deleted_at=deleted_at)
        )

    def _tombstone_crops(self, tenant_id: str, document_id: str) -> int:
        if not self._crop_store or not hasattr(self._crop_store, "tombstone_document"):
            return 0
        return int(self._crop_store.tombstone_document(tenant_id, document_id))

    def _visual_refs(self, tenant_id: str, document_id: str) -> _VisualRefs:
        chunks = ()
        if hasattr(self._store, "visual_chunks_for_document"):
            chunks = tuple(self._store.visual_chunks_for_document(tenant_id, document_id))
        asset_ids = frozenset(
            str(chunk.metadata.get("asset_id", ""))
            for chunk in chunks
            if chunk.metadata.get("asset_id")
        )
        region_ids = frozenset(
            str(chunk.metadata.get("region_id", ""))
            for chunk in chunks
            if chunk.metadata.get("region_id")
        )
        crop_ids: set[str] = set()
        if self._crop_store and hasattr(self._crop_store, "list_document"):
            crop_ids.update(
                crop.crop_id for crop in self._crop_store.list_document(tenant_id, document_id)
            )
        return _VisualRefs(asset_ids=asset_ids, region_ids=region_ids, crop_ids=frozenset(crop_ids))
