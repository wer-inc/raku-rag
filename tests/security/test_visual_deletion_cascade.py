"""T078 - visual deletion cascades through artifacts and caches."""

from __future__ import annotations

import unittest

from raku_rag.domain.models import ScopeType, SubjectType
from tests.helpers import claims, fresh

T = "tenant_a"


class TestVisualDeletionCascade(unittest.TestCase):
    def setUp(self) -> None:
        self.sys = fresh()
        self.alice = claims(T, "alice")
        self.sys.grant(T, ScopeType.COLLECTION, "visual_manuals", SubjectType.USER, "alice")
        self.result = self.sys.ingest_visual_fixture(
            tenant_id=T,
            collection_id="visual_manuals",
            document_id="panel_image",
            image=b"OCR: Pump panel shows alarm AL-42.\ncaption: Pump alarm panel",
        )

    def test_visual_delete_cascades_asset_region_embedding_crop_and_visual_caches(self) -> None:
        asset_id = self.result.asset.asset_id
        crop = self.sys.crops.create_region_crop(self.result.regions[0])
        before = self.sys.answer(self.alice, "what alarm is shown?", "visual_manuals")
        self.assertEqual(before.status, "ok")

        self.sys.cache.put(T, "answer:panel", before, {"panel_image"})
        self.sys.cache.put(T, "thumbnail:asset", {"uri": "thumb"}, set(), asset_ids={asset_id})
        self.sys.cache.put(T, "vlm:asset", {"text": "old"}, set(), asset_ids={asset_id})
        self.sys.cache.put(T, "crop:region", {"uri": crop.crop_uri}, set(), crop_ids={crop.crop_id})

        result = self.sys.deletion.delete(T, "panel_image")

        self.assertEqual(result.tombstoned_visual_assets, 1)
        self.assertEqual(result.tombstoned_visual_regions, 1)
        self.assertEqual(result.tombstoned_visual_embeddings, 1)
        self.assertEqual(result.tombstoned_crops, 1)
        self.assertEqual(result.invalidated_visual_cache_entries, 3)
        self.assertEqual(result.invalidated_cache_entries, 4)
        self.assertIsNone(self.sys.cache.get(T, "answer:panel"))
        self.assertIsNone(self.sys.cache.get(T, "thumbnail:asset"))
        self.assertIsNone(self.sys.cache.get(T, "vlm:asset"))
        self.assertIsNone(self.sys.cache.get(T, "crop:region"))
        self.assertIsNone(self.sys.assets.get_visual_asset(self.alice, asset_id))

    def test_reapply_tombstones_invalidates_restored_visual_asset_cache(self) -> None:
        self.sys.deletion.delete(T, "panel_image")

        restored = self.sys.ingest_visual_fixture(
            tenant_id=T,
            collection_id="visual_manuals",
            document_id="panel_image",
            image=b"OCR: Pump panel shows alarm AL-42.",
        )
        self.sys.cache.put(
            T, "thumbnail:restored", {"uri": "thumb"}, set(), asset_ids={restored.asset.asset_id}
        )
        self.assertIsNotNone(self.sys.assets.get_visual_asset(self.alice, restored.asset.asset_id))

        applied = self.sys.deletion.reapply_tombstones(T)

        self.assertEqual(applied, 1)
        self.assertIsNone(self.sys.assets.get_visual_asset(self.alice, restored.asset.asset_id))
        self.assertIsNone(self.sys.cache.get(T, "thumbnail:restored"))
        self.assertEqual(self.sys.search(self.alice, "AL-42", "visual_manuals"), [])


if __name__ == "__main__":
    unittest.main()
