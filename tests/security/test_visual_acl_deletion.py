"""T064 - visual ACL/deletion hard gate."""

from __future__ import annotations

import unittest

from raku_rag.domain.models import ScopeType, SubjectType
from tests.helpers import claims, fresh

T = "tenant_a"


class TestVisualAclDeletion(unittest.TestCase):
    def setUp(self) -> None:
        self.sys = fresh()
        self.visual_result = self.sys.ingest_visual_fixture(
            tenant_id=T,
            collection_id="visual_manuals",
            document_id="panel_image",
            image=b"OCR: Pump panel shows alarm AL-42.\ncaption: contact alice@example.com for Pump alarm panel",
            exif_metadata={"GPSLatitude": "35.0", "ImageDescription": "owner alice@example.com"},
        )
        self.sys.grant(T, ScopeType.COLLECTION, "visual_manuals", SubjectType.USER, "alice")
        self.alice = claims(T, "alice")
        self.bob = claims(T, "bob")

    def test_unauthorized_visual_asset_never_reaches_search_answer_or_citation(self) -> None:
        search = self.sys.search(self.bob, "alarm AL-42", "visual_manuals")
        answer = self.sys.answer(self.bob, "what alarm is shown?", "visual_manuals")

        self.assertEqual(search, [])
        self.assertEqual(answer.status, "insufficient_evidence")
        self.assertEqual(answer.citations, ())
        self.assertEqual(answer.used_chunks, ())

    def test_deleted_visual_document_does_not_reappear(self) -> None:
        before = self.sys.answer(self.alice, "what alarm is shown?", "visual_manuals")
        self.assertEqual(before.status, "ok")
        self.assertEqual(before.citations[0].kind, "visual")
        crop = self.sys.crops.create_region_crop(self.visual_result.regions[0])

        result = self.sys.deletion.delete(T, "panel_image")
        self.assertGreaterEqual(result.tombstoned_chunks, 1)
        self.assertEqual(result.tombstoned_crops, 1)
        after = self.sys.answer(self.alice, "what alarm is shown?", "visual_manuals")
        search = self.sys.search(self.alice, "alarm AL-42", "visual_manuals")

        self.assertEqual(after.status, "insufficient_evidence")
        self.assertEqual(after.used_chunks, ())
        self.assertEqual(search, [])
        self.assertIsNone(self.sys.crops.store.get(T, crop.crop_id))

    def test_exif_and_caption_pii_are_redacted_before_visual_metadata_use(self) -> None:
        doc = self.sys.registry.get(T, "panel_image")
        self.assertIsNotNone(doc)
        self.assertIn("GPSLatitude", doc.metadata["exif_removed_keys"])
        self.assertNotIn("alice@example.com", self.visual_result.regions[0].generated_caption_text)
        self.assertIn("[REDACTED:email]", self.visual_result.regions[0].generated_caption_text)
        records = self.sys.cost.records(T, kind="captioning_cost")
        self.assertTrue(records)


if __name__ == "__main__":
    unittest.main()
