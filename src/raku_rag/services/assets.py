"""T076 - authorized visual asset view service."""

from __future__ import annotations

from dataclasses import asdict
from typing import Sequence

from raku_rag.core.security.acl import AclPolicy
from raku_rag.domain.models import BoundingBox, Chunk, CropArtifact, Document, IdentityClaims


class AssetService:
    def __init__(self, registry, store, acl: AclPolicy, crop_store=None) -> None:
        self._registry = registry
        self._store = store
        self._acl = acl
        self._crop_store = crop_store

    def get_visual_asset(self, principal: IdentityClaims, asset_id: str) -> dict | None:
        chunks = self._visual_chunks(principal.tenant_id, asset_id)
        if not chunks:
            return None
        doc = self._registry.get(principal.tenant_id, chunks[0].document_id)
        if doc is None or doc.tombstone or not self._acl.can_read_document(principal, doc):
            return None
        regions = [_region_json(chunk) for chunk in chunks if chunk.document_id == doc.document_id]
        return {
            "asset_id": asset_id,
            "tenant_id": doc.tenant_id,
            "collection_id": doc.collection_id,
            "document_id": doc.document_id,
            "source_id": doc.source_id,
            "version": doc.version,
            "storage_uri": str(doc.metadata.get("visual_asset_storage_uri") or ""),
            "content_type": str(doc.metadata.get("visual_asset_content_type") or ""),
            "page_number": int(_first_metadata(chunks, "page_number") or 0),
            "regions": regions,
            "crops": [_crop_json(crop) for crop in self._authorized_crops(doc, asset_id)],
        }

    def _visual_chunks(self, tenant_id: str, asset_id: str) -> tuple[Chunk, ...]:
        if hasattr(self._store, "visual_chunks_for_asset"):
            return tuple(self._store.visual_chunks_for_asset(tenant_id, asset_id))
        return ()

    def _authorized_crops(self, doc: Document, asset_id: str) -> tuple[CropArtifact, ...]:
        if self._crop_store is None or not hasattr(self._crop_store, "list_document"):
            return ()
        return tuple(
            crop
            for crop in self._crop_store.list_document(doc.tenant_id, doc.document_id)
            if crop.asset_id == asset_id and not crop.tombstone
        )


def _region_json(chunk: Chunk) -> dict:
    return {
        "region_id": str(chunk.metadata.get("region_id") or chunk.chunk_id),
        "chunk_id": chunk.chunk_id,
        "region_type": str(chunk.metadata.get("region_type") or "text"),
        "page_number": int(chunk.metadata.get("page_number") or 0),
        "bbox": _bbox_json(_bbox_from_metadata(chunk)),
        "crop_uri": str(chunk.metadata.get("crop_uri") or ""),
    }


def _crop_json(crop: CropArtifact) -> dict:
    return {
        "crop_id": crop.crop_id,
        "asset_id": crop.asset_id,
        "region_id": crop.region_id,
        "crop_uri": crop.crop_uri,
        "bbox": asdict(crop.bbox),
        "redaction_policy_ref": crop.redaction_policy_ref,
    }


def _bbox_from_metadata(chunk: Chunk) -> BoundingBox:
    raw = chunk.metadata.get("bbox") or {}
    if isinstance(raw, BoundingBox):
        return raw
    if not isinstance(raw, dict):
        return BoundingBox(0.0, 0.0, 0.0, 0.0)
    return BoundingBox(
        x=float(raw.get("x", 0.0) or 0.0),
        y=float(raw.get("y", 0.0) or 0.0),
        width=float(raw.get("width", 0.0) or 0.0),
        height=float(raw.get("height", 0.0) or 0.0),
    )


def _bbox_json(bbox: BoundingBox) -> dict:
    return {"x": bbox.x, "y": bbox.y, "width": bbox.width, "height": bbox.height}


def _first_metadata(chunks: Sequence[Chunk], key: str) -> object:
    for chunk in chunks:
        value = chunk.metadata.get(key)
        if value not in (None, ""):
            return value
    return None


__all__ = ["AssetService"]
