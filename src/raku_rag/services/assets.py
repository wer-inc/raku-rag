"""T076 - authorized visual asset view service."""

from __future__ import annotations

from dataclasses import asdict
from typing import Sequence

from raku_rag.core.security.acl import AclPolicy
from raku_rag.domain.models import BoundingBox, Chunk, CropArtifact, Document, IdentityClaims
from raku_rag.services.crop import REDACTED_CROP_URI_PREFIX


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
        regions = [
            _region_json(chunk, crop_store=self._crop_store)
            for chunk in chunks
            if chunk.document_id == doc.document_id
        ]
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
            "crops": [
                _crop_json(crop, crop_store=self._crop_store)
                for crop in self._authorized_crops(doc, asset_id)
            ],
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


def _region_json(chunk: Chunk, *, crop_store=None) -> dict:
    redaction_required = _metadata_bool(chunk.metadata, "visual_region_redaction_required")
    crop_uri = _public_region_crop_uri(chunk, redaction_required=redaction_required)
    crop_url = _public_crop_url(crop_uri, crop_store=crop_store)
    return {
        "region_id": str(chunk.metadata.get("region_id") or chunk.chunk_id),
        "chunk_id": chunk.chunk_id,
        "region_type": str(chunk.metadata.get("region_type") or "text"),
        "page_number": int(chunk.metadata.get("page_number") or 0),
        "bbox": _bbox_json(_bbox_from_metadata(chunk)),
        "crop_uri": "" if crop_uri.startswith("s3://") else crop_uri,
        "crop_url": crop_url,
        "sensitive_detected": _metadata_bool(chunk.metadata, "sensitive_detected"),
        "sensitive_detection_labels": _metadata_labels(chunk.metadata),
        "visual_region_redaction_required": redaction_required,
        "visual_region_redaction_status": str(
            chunk.metadata.get("visual_region_redaction_status") or "not_required"
        ),
        "visual_redaction_policy_ref": str(chunk.metadata.get("visual_redaction_policy_ref") or ""),
    }


def _crop_json(crop: CropArtifact, *, crop_store=None) -> dict:
    redaction_required = _metadata_bool(crop.metadata, "visual_region_redaction_required")
    crop_uri = _public_crop_uri(crop, redaction_required=redaction_required)
    crop_url = _public_crop_url(crop_uri, crop_store=crop_store)
    return {
        "crop_id": crop.crop_id,
        "asset_id": crop.asset_id,
        "region_id": crop.region_id,
        "crop_uri": "" if crop_uri.startswith("s3://") else crop_uri,
        "crop_url": crop_url,
        "bbox": asdict(crop.bbox),
        "redaction_policy_ref": crop.redaction_policy_ref,
        "sensitive_detected": _metadata_bool(crop.metadata, "sensitive_detected"),
        "sensitive_detection_labels": _metadata_labels(crop.metadata),
        "visual_region_redaction_required": redaction_required,
        "visual_region_redaction_status": str(
            crop.metadata.get("visual_region_redaction_status") or "not_required"
        ),
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


def _public_region_crop_uri(chunk: Chunk, *, redaction_required: bool) -> str:
    raw = str(chunk.metadata.get("crop_uri") or "")
    if not redaction_required:
        return raw
    redacted = str(chunk.metadata.get("redacted_crop_uri") or "")
    if redacted:
        return redacted
    asset_id = str(chunk.metadata.get("asset_id") or "")
    region_id = str(chunk.metadata.get("region_id") or chunk.chunk_id)
    if asset_id and region_id:
        return f"{REDACTED_CROP_URI_PREFIX}/{chunk.tenant_id}/crop:{asset_id}:{region_id}"
    return ""


def _public_crop_uri(crop: CropArtifact, *, redaction_required: bool) -> str:
    if not redaction_required:
        return crop.crop_uri
    return str(crop.metadata.get("redacted_crop_uri") or "")


def _public_crop_url(crop_uri: str, *, crop_store=None) -> str:
    if not crop_uri:
        return ""
    if not crop_uri.startswith("s3://"):
        return crop_uri
    public_url = getattr(crop_store, "public_url", None)
    if not callable(public_url):
        return ""
    return str(public_url(crop_uri))


def _metadata_bool(metadata: dict, key: str) -> bool:
    value = metadata.get(key)
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "required"}
    return bool(value)


def _metadata_labels(metadata: dict) -> list[str]:
    labels = metadata.get("sensitive_detection_labels") or []
    if isinstance(labels, tuple):
        labels = list(labels)
    if not isinstance(labels, list):
        return []
    return sorted(str(label) for label in labels)


__all__ = ["AssetService"]
