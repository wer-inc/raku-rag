"""T019 — Manufacturing search overlay: 001 retrieval + manufacturing metadata filter + approval tags.

Reuses the 001 ``RetrievalService`` (ACL pre-filter, tombstone, tenancy) unchanged and ADDS:
  - ``manufacturing_filters`` mapped onto the 001 metadata filter (candidate post-filter; never
    weakens ACL/tenancy), and
  - ``approval_status`` / ``effective_date`` on each result (latest_approved / obsolete / 有効日の識別,
    contracts §A POST /v1/search; US2-2).

US2 (FR-MFG-002): a spreadsheet-derived chunk carries a ``sheet!R{row}C{col}`` cell anchor in its
normalized text (emitted by ``SpreadsheetParser``); this overlay parses it back out and exposes the
cell coordinate on the result as ``cell_anchor`` (+ structured ``sheet`` / ``row`` / ``col``) so a
citation resolves to a single cell — preserved through the reused 001 ingest/chunk/citation path.

stdlib only.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from raku_rag.domain.models import IdentityClaims, QueryProfile, ScoredChunk
from raku_rag.manufacturing.domain.metadata import ManufacturingDocumentMetadata
from raku_rag.providers.parsers import parse_cell_anchor
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
    approval_source: str | None = None
    # FR-MFG-002 spreadsheet cell coordinate (None for non-spreadsheet chunks).
    cell_anchor: str | None = None
    sheet: str | None = None
    row: int | None = None
    col: int | None = None


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
            # FR-MFG-002: recover the spreadsheet cell coordinate from the chunk's normalized text.
            anchor = parse_cell_anchor(s.chunk.text)
            cell_anchor = sheet = None
            row = col = None
            if anchor is not None:
                sheet, row, col = anchor
                cell_anchor = f"{sheet}!R{row}C{col}"
            results.append(
                ManufacturingSearchResult(
                    chunk_id=s.chunk.chunk_id,
                    document_id=s.chunk.document_id,
                    collection_id=s.chunk.collection_id,
                    retrieval_score=s.retrieval_score,
                    approval_status=(meta.approval_status.value if meta else None),
                    effective_date=(meta.effective_date if meta else None),
                    approval_source=(meta.approval_source.value if meta else None),
                    cell_anchor=cell_anchor,
                    sheet=sheet,
                    row=row,
                    col=col,
                )
            )
        return results
