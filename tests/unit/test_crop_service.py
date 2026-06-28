from __future__ import annotations

from io import BytesIO
import unittest

from raku_rag.domain.models import BoundingBox, LayoutRegion
from raku_rag.services.crop import CropService, S3CropStore
from tests.unit.test_connectors import FakeS3Client


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
        self.assertFalse(crop.metadata["visual_region_redaction_required"])
        self.assertEqual(crop.metadata["raw_crop_uri"], crop.crop_uri)
        self.assertEqual(crop.metadata["redacted_crop_uri"], "")
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

    def test_sensitive_region_crop_requires_visual_redaction_policy(self) -> None:
        service = CropService()
        region = self.region()
        region.metadata = {
            "sensitive_detected": True,
            "sensitive_detection_labels": ["email", "api_key"],
            "visual_region_redaction_required": True,
            "pii_redaction_policy_ref": "default-regex-v1",
        }

        crop = service.create_region_crop(region)

        self.assertEqual(crop.redaction_policy_ref, "visual-region-redaction-required")
        self.assertTrue(crop.metadata["visual_region_redaction_required"])
        self.assertEqual(crop.metadata["visual_region_redaction_status"], "required")
        self.assertEqual(crop.metadata["sensitive_detection_labels"], ["api_key", "email"])
        self.assertEqual(crop.metadata["raw_crop_uri"], crop.crop_uri)
        self.assertTrue(crop.metadata["redacted_crop_uri"].startswith("memory://redacted-crops/"))

    def test_s3_crop_store_materializes_raw_and_redacted_objects(self) -> None:
        from raku_rag.providers.connectors import S3Connector

        client = FakeS3Client({})
        store = S3CropStore(
            "s3://docs/visual-crops",
            connector=S3Connector(bucket="docs", client=client),
        )
        service = CropService(store)
        region = self.region()
        region.metadata = {
            "sensitive_detected": True,
            "sensitive_detection_labels": ["email"],
            "visual_region_redaction_required": True,
        }

        crop = service.create_region_crop(region, raw_bytes=b"raw-png", redacted_bytes=b"redacted")

        self.assertTrue(crop.crop_uri.startswith("s3://docs/visual-crops/tenant_a/manuals/"))
        self.assertTrue(crop.metadata["redacted_crop_uri"].startswith("s3://docs/visual-crops/"))
        self.assertIn(("docs", crop.crop_uri.removeprefix("s3://docs/")), client.objects)
        self.assertEqual(client.objects[("docs", crop.crop_uri.removeprefix("s3://docs/"))], b"raw-png")
        self.assertEqual(store.public_url(crop.crop_uri), f"https://signed.example/docs/{crop.crop_uri.removeprefix('s3://docs/')}?ttl=300")

    def test_s3_crop_store_materializes_bbox_png_when_image_bytes_are_available(self) -> None:
        try:
            from PIL import Image  # type: ignore
        except Exception:
            self.skipTest("Pillow is not installed")
        from raku_rag.providers.connectors import S3Connector

        source = Image.new("RGB", (10, 10), color=(255, 255, 255))
        for x in range(1, 4):
            for y in range(2, 6):
                source.putpixel((x, y), (255, 0, 0))
        raw = BytesIO()
        source.save(raw, format="PNG")
        client = FakeS3Client({})
        store = S3CropStore(
            "s3://docs/visual-crops",
            connector=S3Connector(bucket="docs", client=client),
        )
        service = CropService(store)

        crop = service.create_region_crop(self.region(), raw_bytes=raw.getvalue())

        stored = client.objects[("docs", crop.crop_uri.removeprefix("s3://docs/"))]
        with Image.open(BytesIO(stored)) as rendered:
            self.assertEqual(rendered.size, (3, 4))
            self.assertEqual(rendered.getpixel((0, 0))[:3], (255, 0, 0))
        self.assertEqual(crop.metadata["crop_render_status"], "rendered")


if __name__ == "__main__":
    unittest.main()
