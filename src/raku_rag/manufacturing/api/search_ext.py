"""T019 — Manufacturing search overlay: 001 retrieval + manufacturing metadata filter + approval tags.

Reuses the 001 ``RetrievalService`` (ACL pre-filter, tombstone, tenancy) unchanged and ADDS:
  - ``manufacturing_filters`` mapped onto the 001 metadata filter (candidate post-filter; never
    weakens ACL/tenancy), and
  - ``approval_status`` / ``effective_date`` on each result (latest_approved / obsolete / 有効日の識別,
    contracts §A POST /v1/search; US2-2).

NOTE (scope): XLSX/CSV CELL-coordinate citation (``sheet`` / ``row`` / ``col`` on the citation range,
FR-MFG-002) is **US2** and intentionally NOT implemented here — see contracts §A and §1. This module
covers only the US1 metadata-filter + approval-tag extension.

stdlib only.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from raku_rag.domain.models import IdentityClaims, QueryProfile, ScoredChunk
from raku_rag.manufacturing.domain.metadata import ManufacturingDocumentMetadata
from raku_rag.services.retrieval import RetrievalService

GetMfgMeta = Callable[[str, str], ManufacturingDocumentMetadata | None]


@dataclass(frozen=True)
class ManufacturingSearchResult:
    """A 001 search result + manufacturing approval tags (contracts §A POST /v1/search)."""

    chunk_id: str
    document_id: str
    collection_id: str
    retrieval_score: float
    approval_status: str | None = None
    effective_date: str | None = None


def _matches_filters(meta: ManufacturingDocumentMetadata | None, filters: dict | None) -> bool:
    if not filters:
        return True
    if meta is None:
        return False
    for key, want in filters.items():
        if want is None:
            continue
        got = getattr(meta, key, None)
        if got is None and key == "document_type":
            got = getattr(meta, "document_kind", None)
        if hasattr(got, "value"):
            got = got.value
        if got != want:
            return False
    return True


class ManufacturingSearchService:
    def __init__(self, *, retrieval: RetrievalService, get_mfg_meta: GetMfgMeta) -> None:
        self._retrieval = retrieval
        self._get_mfg_meta = get_mfg_meta

    def search(
        self,
        principal: IdentityClaims,
        query: str,
        profile: QueryProfile,
        *,
        manufacturing_filters: dict | None = None,
    ) -> list[ManufacturingSearchResult]:
        scored: list[ScoredChunk] = list(self._retrieval.retrieve(principal, query, profile))
        results: list[ManufacturingSearchResult] = []
        for s in scored:
            meta = self._get_mfg_meta(principal.tenant_id, s.chunk.document_id)
            if not _matches_filters(meta, manufacturing_filters):
                continue
            results.append(
                ManufacturingSearchResult(
                    chunk_id=s.chunk.chunk_id,
                    document_id=s.chunk.document_id,
                    collection_id=s.chunk.collection_id,
                    retrieval_score=s.retrieval_score,
                    approval_status=(meta.approval_status.value if meta else None),
                    effective_date=(meta.effective_date if meta else None),
                )
            )
        return results
