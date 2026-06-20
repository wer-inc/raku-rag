"""T074 - visual crop generation with inheritance rules."""

from __future__ import annotations

from dataclasses import dataclass, field

from raku_rag.domain.models import CropArtifact, LayoutRegion


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
        crop = CropArtifact(
            tenant_id=region.tenant_id,
            collection_id=region.collection_id,
            document_id=region.document_id,
            asset_id=region.asset_id,
            region_id=region.region_id,
            crop_id=crop_id,
            bbox=region.bbox,
            crop_uri=f"memory://crops/{region.tenant_id}/{crop_id}",
            redaction_policy_ref=redaction_policy_ref,
            metadata={
                "inherits_acl_from_document_id": region.document_id,
                "inherits_redaction_from_region_id": region.region_id,
                "source_page_number": region.page_number,
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


__all__ = ["CropService", "InMemoryCropStore"]
