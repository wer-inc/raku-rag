"""T027 — MetadataEnricher: attach manufacturing + approval metadata at ingest (FR-MFG-003).

The enricher takes the per-document ``ManufacturingDocumentMetadata`` (mfg tags + approval metadata)
and attaches it to the REUSED 001 ``Document.metadata`` JSON under a stable key, AND propagates it to
every ``Chunk.metadata`` of that document so the 001 metadata-filter path ([base:FR-010]) and the
US1 HighRiskClassifier / SafetyGate can read it without a second lookup.

This does NOT define a new store: the document body, chunks and index are produced by the reused 001
ingestion path; the enricher only decorates the already-persisted Document/Chunk objects. ``tenant_id``
on the metadata MUST match the document (001 tenancy is the hard isolation boundary, [base:FR-021]).

stdlib only. Structurally satisfies ``raku_rag.manufacturing.interfaces.MetadataEnricher``.
"""

from __future__ import annotations

from typing import Callable

from raku_rag.core.errors import TenantIsolationError
from raku_rag.domain.models import Document
from raku_rag.manufacturing.domain.metadata import ManufacturingDocumentMetadata
from raku_rag.providers.vectorstores import InMemoryVectorStore

# Key under which the ManufacturingDocumentMetadata is stashed in the 001 Document/Chunk metadata JSON.
MFG_META_KEY = "_mfg_meta"

GetDocument = Callable[[str, str], Document | None]


class MetadataEnricher:
    """Attach ManufacturingDocumentMetadata to the 001 Document.metadata + propagate to chunks.

    ``enrich`` matches the ABC signature (``doc_ref``, ``raw_metadata``) for interface parity, but the
    manufacturing ingestion path calls :meth:`attach` with the already-built typed metadata (the common
    case) — both land the same metadata under :data:`MFG_META_KEY`.
    """

    def __init__(self, *, store: InMemoryVectorStore, get_document: GetDocument) -> None:
        self._store = store
        self._get_document = get_document

    # --- typed attach (manufacturing ingestion path) ---------------------------------------------
    def attach(
        self,
        tenant_id: str,
        document_id: str,
        metadata: ManufacturingDocumentMetadata,
    ) -> ManufacturingDocumentMetadata:
        """Stash ``metadata`` on the Document and every Chunk of ``(tenant_id, document_id)``."""
        if metadata.tenant_id and metadata.tenant_id != tenant_id:
            # Cross-tenant metadata attach is forbidden (001 tenancy boundary).
            raise TenantIsolationError("resource not found")
        doc = self._get_document(tenant_id, document_id)
        if doc is not None:
            doc.metadata[MFG_META_KEY] = metadata
        self.propagate_to_chunks(tenant_id, document_id, metadata)
        return metadata

    def propagate_to_chunks(
        self,
        tenant_id: str,
        document_id: str,
        metadata: ManufacturingDocumentMetadata,
    ) -> int:
        """Write the metadata reference onto each indexed Chunk.metadata (FR-MFG-003). Returns count."""
        n = 0
        for chunk, _vec in self._store._items.values():
            if chunk.tenant_id == tenant_id and chunk.document_id == document_id:
                chunk.metadata[MFG_META_KEY] = metadata
                n += 1
        return n

    # --- ABC parity (raw dict -> typed) ----------------------------------------------------------
    def enrich(self, doc_ref: str, raw_metadata: dict) -> ManufacturingDocumentMetadata:
        """Build typed metadata from a raw dict for ``doc_ref`` (``tenant_id/document_id``)."""
        tenant_id, _, document_id = doc_ref.partition("/")
        meta = ManufacturingDocumentMetadata(
            tenant_id=tenant_id or raw_metadata.get("tenant_id", ""),
            document_id=document_id or raw_metadata.get("document_id", ""),
            **{k: v for k, v in raw_metadata.items() if k not in ("tenant_id", "document_id")},
        )
        return self.attach(meta.tenant_id, meta.document_id, meta)
