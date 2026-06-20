"""T019 — VectorStore. MVP in-memory analog of the pgvector adapter.

CRITICAL invariant (FR-022, SC-003/004, SC-009): search applies tenant_id, tombstone exclusion
and the ACL ``visible`` predicate as a PRE-filter, BEFORE scoring — never post-filter only. The
production pgvector adapter expresses the same filter as a SQL WHERE clause.
"""

from __future__ import annotations

from typing import Sequence

from raku_rag.domain.models import Chunk, Modality, ScoredChunk
from raku_rag.interfaces.base import VectorStore, Vector, VisibilityPredicate
from raku_rag.providers.embeddings import cosine


class InMemoryVectorStore(VectorStore):
    def __init__(self) -> None:
        # chunk_id -> (Chunk, vector)
        self._items: dict[str, tuple[Chunk, Vector]] = {}
        # observability for tests: how many candidates were considered after pre-filter
        self.last_prefiltered_count: int = 0

    def upsert(self, chunks: Sequence[tuple[Chunk, Vector]]) -> None:
        for chunk, vec in chunks:
            self._items[chunk.chunk_id] = (chunk, vec)

    def iter_items(self) -> tuple[tuple[Chunk, Vector], ...]:
        """All stored (chunk, vector) pairs — the in-memory bulk accessor.

        A public seam for callers that need to scan the whole store (e.g. metadata propagation,
        the manufacturing ACL-denial survey) so they don't reach into the private ``_items`` dict.
        """
        return tuple(self._items.values())

    def search(
        self,
        tenant_id: str,
        query_vec: Vector,
        *,
        visible: VisibilityPredicate,
        top_k: int,
    ) -> list[ScoredChunk]:
        candidates: list[tuple[Chunk, Vector]] = []
        for chunk, vec in self._items.values():
            # PRE-filter: tenant boundary + tombstone + ACL visibility (deny-by-default)
            if chunk.tenant_id != tenant_id:
                continue
            if chunk.tombstone:
                continue
            if not visible(chunk):
                continue
            candidates.append((chunk, vec))
        self.last_prefiltered_count = len(candidates)
        scored = [ScoredChunk(chunk=c, retrieval_score=cosine(query_vec, v)) for c, v in candidates]
        scored.sort(key=lambda s: s.retrieval_score, reverse=True)
        return scored[:top_k]

    def set_tombstone(self, tenant_id: str, document_id: str, value: bool) -> int:
        n = 0
        for cid, (chunk, vec) in list(self._items.items()):
            if chunk.tenant_id == tenant_id and chunk.document_id == document_id:
                chunk.tombstone = value
                n += 1
        return n

    def purge(self, tenant_id: str, document_id: str) -> int:
        to_del = [
            cid
            for cid, (chunk, _) in self._items.items()
            if chunk.tenant_id == tenant_id and chunk.document_id == document_id
        ]
        for cid in to_del:
            del self._items[cid]
        return len(to_del)

    def visual_chunks_for_asset(self, tenant_id: str, asset_id: str) -> tuple[Chunk, ...]:
        return tuple(
            chunk
            for chunk, _ in self._items.values()
            if chunk.tenant_id == tenant_id
            and not chunk.tombstone
            and (chunk.modality == Modality.VISUAL or str(chunk.modality) == Modality.VISUAL.value)
            and str(chunk.metadata.get("asset_id", "")) == asset_id
        )

    def visual_chunks_for_document(self, tenant_id: str, document_id: str) -> tuple[Chunk, ...]:
        return tuple(
            chunk
            for chunk, _ in self._items.values()
            if chunk.tenant_id == tenant_id
            and chunk.document_id == document_id
            and not chunk.tombstone
            and (chunk.modality == Modality.VISUAL or str(chunk.modality) == Modality.VISUAL.value)
        )
