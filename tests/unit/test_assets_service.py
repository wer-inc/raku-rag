"""T076 - authorized visual asset service."""

from __future__ import annotations

import unittest

from raku_rag.domain.models import ScopeType, SubjectType
from raku_rag.services.assets import AssetService
from tests.helpers import claims, fresh

T = "tenant_a"


class TestAssetService(unittest.TestCase):
    def setUp(self) -> None:
        self.sys = fresh()
        self.alice = claims(T, "alice")
        self.bob = claims(T, "bob")
        self.result = self.sys.ingest_visual_fixture(
            tenant_id=T,
            collection_id="manuals",
            document_id="panel_image",
            image=b"OCR: Pump panel shows alarm AL-42.\ncaption: contact alice@example.com",
        )
        self.sys.grant(T, ScopeType.COLLECTION, "manuals", SubjectType.USER, "alice")

    def test_authorized_asset_view_includes_regions_and_inherited_crops(self) -> None:
        crop = self.sys.crops.create_region_crop(self.result.regions[0])

        asset = self.sys.assets.get_visual_asset(self.alice, self.result.asset.asset_id)

        self.assertIsNotNone(asset)
        assert asset is not None
        self.assertEqual(asset["asset_id"], self.result.asset.asset_id)
        self.assertEqual(asset["document_id"], "panel_image")
        self.assertEqual(asset["regions"][0]["region_id"], self.result.regions[0].region_id)
        self.assertEqual(asset["regions"][0]["bbox"]["width"], self.result.regions[0].bbox.width)
        self.assertEqual(asset["crops"][0]["crop_id"], crop.crop_id)
        self.assertTrue(asset["regions"][0]["visual_region_redaction_required"])
        self.assertIn("email", asset["regions"][0]["sensitive_detection_labels"])
        self.assertEqual(
            asset["crops"][0]["redaction_policy_ref"], "visual-region-redaction-required"
        )
        self.assertTrue(asset["crops"][0]["visual_region_redaction_required"])
        self.assertTrue(asset["regions"][0]["crop_uri"].startswith("memory://redacted-crops/"))
        self.assertTrue(asset["crops"][0]["crop_uri"].startswith("memory://redacted-crops/"))
        self.assertNotEqual(asset["crops"][0]["crop_uri"], crop.crop_uri)
        self.assertNotIn("ocr_text", asset["regions"][0])
        self.assertNotIn("generated_caption_text", asset["regions"][0])

    def test_region_crop_url_can_be_presigned_from_persisted_chunk_metadata(self) -> None:
        class FakeCropStore:
            def list_document(self, tenant_id: str, document_id: str):
                return ()

            def public_url(self, uri: str) -> str:
                return f"https://signed.example/{uri.removeprefix('s3://')}"

        for chunk, _vec in self.sys.store.iter_items():
            if chunk.metadata.get("asset_id") == self.result.asset.asset_id:
                chunk.metadata["crop_uri"] = "s3://docs/visual-crops/tenant/doc/crop.png"
                chunk.metadata["visual_region_redaction_required"] = False

        service = AssetService(self.sys.registry, self.sys.store, self.sys.acl, FakeCropStore())
        asset = service.get_visual_asset(self.alice, self.result.asset.asset_id)

        self.assertIsNotNone(asset)
        assert asset is not None
        self.assertEqual(asset["regions"][0]["crop_uri"], "")
        self.assertEqual(
            asset["regions"][0]["crop_url"],
            "https://signed.example/docs/visual-crops/tenant/doc/crop.png",
        )

    def test_unauthorized_or_deleted_asset_returns_none(self) -> None:
        self.assertIsNone(self.sys.assets.get_visual_asset(self.bob, self.result.asset.asset_id))

        self.sys.deletion.delete(T, "panel_image")

        self.assertIsNone(self.sys.assets.get_visual_asset(self.alice, self.result.asset.asset_id))


if __name__ == "__main__":
    unittest.main()
