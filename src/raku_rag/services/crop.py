"""T074 - visual crop generation with inheritance rules."""

from __future__ import annotations

from dataclasses import dataclass, field

from raku_rag.domain.models import CropArtifact, LayoutRegion
from raku_rag.workers.ingestion import VISUAL_REGION_REDACTION_REQUIRED_REF

REDACTED_CROP_URI_PREFIX = "memory://redacted-crops"


@dataclass
class InMemoryCropStore:
    _crops: dict[tuple[str, str], CropArtifact] = field(default_factory=dict)

    def put(self, crop: CropArtifact) -> CropArtifact:
        self._crops[(crop.tenant_id, crop.crop_id)] = crop
        return crop

    def get(self, tenant_id: str, crop_id: str) -> CropArtifact | None:
        crop = self._crops.get((tenant_id, crop_id))
        if crop is None or crop.tombstone:
            return None
        return crop

    def list_document(self, tenant_id: str, document_id: str) -> tuple[CropArtifact, ...]:
        return tuple(
            crop
            for (t, _), crop in self._crops.items()
            if t == tenant_id and crop.document_id == document_id and not crop.tombstone
        )

    def tombstone_document(self, tenant_id: str, document_id: str) -> int:
        count = 0
        for (t, _), crop in self._crops.items():
            if t == tenant_id and crop.document_id == document_id and not crop.tombstone:
                crop.tombstone = True
                count += 1
        return count


class CropService:
    def __init__(self, store: InMemoryCropStore | None = None) -> None:
        self.store = store or InMemoryCropStore()

    def create_region_crop(
        self,
        region: LayoutRegion,
        *,
        redaction_policy_ref: str = "inherit",
    ) -> CropArtifact:
        crop_id = f"crop:{region.asset_id}:{region.region_id}"
        labels = _sensitive_labels(region)
        redaction_required = bool(
            region.metadata.get("visual_region_redaction_required")
            or region.metadata.get("sensitive_detected")
            or labels
        )
        effective_redaction_ref = (
            VISUAL_REGION_REDACTION_REQUIRED_REF
            if redaction_policy_ref == "inherit" and redaction_required
            else redaction_policy_ref
        )
        crop = CropArtifact(
            tenant_id=region.tenant_id,
            collection_id=region.collection_id,
            document_id=region.document_id,
            asset_id=region.asset_id,
            region_id=region.region_id,
            crop_id=crop_id,
            bbox=region.bbox,
            crop_uri=f"memory://crops/{region.tenant_id}/{crop_id}",
            redaction_policy_ref=effective_redaction_ref,
            metadata={
                "inherits_acl_from_document_id": region.document_id,
                "inherits_redaction_from_region_id": region.region_id,
                "source_page_number": region.page_number,
                "raw_crop_uri": f"memory://crops/{region.tenant_id}/{crop_id}",
                "redacted_crop_uri": (
                    _redacted_crop_uri(region.tenant_id, crop_id) if redaction_required else ""
                ),
                "sensitive_detected": bool(region.metadata.get("sensitive_detected") or labels),
                "sensitive_detection_labels": labels,
                "pii_redaction_policy_ref": str(
                    region.metadata.get("pii_redaction_policy_ref") or ""
                ),
                "visual_region_redaction_required": redaction_required,
                "visual_region_redaction_status": (
                    "required" if redaction_required else "not_required"
                ),
            },
            tombstone=region.tombstone,
        )
        return self.store.put(crop)

    def get_authorized_crop(
        self, tenant_id: str, crop_id: str, *, document_visible: bool
    ) -> CropArtifact | None:
        if not document_visible:
            return None
        return self.store.get(tenant_id, crop_id)


def _sensitive_labels(region: LayoutRegion) -> list[str]:
    labels = region.metadata.get("sensitive_detection_labels") or []
    if isinstance(labels, tuple):
        labels = list(labels)
    if not isinstance(labels, list):
        return []
    return sorted(str(label) for label in labels)


def _redacted_crop_uri(tenant_id: str, crop_id: str) -> str:
    return f"{REDACTED_CROP_URI_PREFIX}/{tenant_id}/{crop_id}"


__all__ = ["CropService", "InMemoryCropStore"]
