from __future__ import annotations

import unittest

from raku_rag.domain.models import BoundingBox, LayoutRegion
from raku_rag.services.crop import CropService


class TestCropService(unittest.TestCase):
    def region(self, *, tombstone: bool = False, region_id: str = "region_1") -> LayoutRegion:
        return LayoutRegion(
            tenant_id="tenant_a",
            collection_id="manuals",
            document_id="doc_visual",
            asset_id="asset_1",
            region_id=region_id,
            bbox=BoundingBox(0.1, 0.2, 0.3, 0.4),
            page_number=2,
            ocr_text="Pump panel shows alarm AL-42.",
            tombstone=tombstone,
        )

    def test_crop_inherits_tenant_acl_redaction_and_region_bbox(self) -> None:
        service = CropService()

        crop = service.create_region_crop(self.region())

        self.assertEqual(crop.tenant_id, "tenant_a")
        self.assertEqual(crop.collection_id, "manuals")
        self.assertEqual(crop.document_id, "doc_visual")
        self.assertEqual(crop.asset_id, "asset_1")
        self.assertEqual(crop.region_id, "region_1")
        self.assertEqual(crop.bbox, BoundingBox(0.1, 0.2, 0.3, 0.4))
        self.assertEqual(crop.redaction_policy_ref, "inherit")
        self.assertEqual(crop.metadata["inherits_acl_from_document_id"], "doc_visual")
        self.assertEqual(crop.metadata["inherits_redaction_from_region_id"], "region_1")
        self.assertIs(
            service.get_authorized_crop("tenant_a", crop.crop_id, document_visible=True), crop
        )
        self.assertIsNone(
            service.get_authorized_crop("tenant_a", crop.crop_id, document_visible=False)
        )

    def test_crop_inherits_tombstone_and_document_tombstone_hides_existing_crops(self) -> None:
        service = CropService()
        tombstoned = service.create_region_crop(
            self.region(tombstone=True, region_id="region_deleted")
        )
        live = service.create_region_crop(self.region(region_id="region_live"))

        self.assertIsNone(service.store.get("tenant_a", tombstoned.crop_id))
        self.assertEqual(service.store.tombstone_document("tenant_a", "doc_visual"), 1)
        self.assertIsNone(service.store.get("tenant_a", live.crop_id))


if __name__ == "__main__":
    unittest.main()
