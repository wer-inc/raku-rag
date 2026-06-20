"""T063/T063b - visual fixture ingestion and visual citation answer path."""

from __future__ import annotations

import unittest

from raku_rag.domain.models import ScopeType, SubjectType
from tests.helpers import claims, fresh

T = "tenant_a"


class TestVisualAnswer(unittest.TestCase):
    def setUp(self) -> None:
        self.sys = fresh()
        self.alice = claims(T, "alice")
        self.sys.grant(T, ScopeType.COLLECTION, "manuals", SubjectType.USER, "alice")

    def test_visual_answer_returns_visual_citation_and_used_modality(self) -> None:
        result = self.sys.ingest_visual_fixture(
            tenant_id=T,
            collection_id="manuals",
            document_id="panel_image",
            image=b"OCR: Pump panel shows alarm AL-42.\ncaption: Pump alarm panel",
            exif_metadata={"GPSLatitude": "35.0", "ColorSpace": "sRGB"},
        )

        ans = self.sys.answer(self.alice, "what alarm does the pump panel show?", "manuals")

        self.assertEqual(result.caption_status, "succeeded")
        self.assertEqual(ans.status, "ok")
        self.assertIn("AL-42", ans.text or "")
        self.assertIn("visual", ans.used_modalities)
        self.assertEqual(ans.citations[0].kind, "visual")
        self.assertEqual(ans.citations[0].asset_id, result.asset.asset_id)
        self.assertEqual(ans.citations[0].region_id, result.regions[0].region_id)
        self.assertEqual(ans.citations[0].page_number, 1)
        self.assertIsNotNone(ans.citations[0].bbox)
        self.assertNotIn("GPSLatitude", result.asset.metadata["exif"])

    def test_captioning_disabled_still_answers_from_ocr_without_caption_cost(self) -> None:
        result = self.sys.ingest_visual_fixture(
            tenant_id=T,
            collection_id="manuals",
            document_id="panel_image",
            image=b"OCR: Pump panel shows alarm AL-42.\ncaption: Pump alarm panel",
            captioning_enabled=False,
        )

        ans = self.sys.answer(self.alice, "what alarm does the pump panel show?", "manuals")

        self.assertEqual(result.caption_status, "not_requested")
        self.assertEqual(ans.status, "ok")
        self.assertIn("visual", ans.used_modalities)
        self.assertEqual(self.sys.cost.records(T, kind="captioning_cost"), ())

    def test_caption_only_visual_context_is_not_primary_evidence(self) -> None:
        self.sys.ingest_visual_fixture(
            tenant_id=T,
            collection_id="manuals",
            document_id="caption_only",
            image=b"caption: Pump panel shows alarm AL-42.",
        )

        ans = self.sys.answer(self.alice, "what alarm does the pump panel show?", "manuals")

        self.assertEqual(ans.status, "insufficient_evidence")
        self.assertEqual(ans.used_chunks, ())


if __name__ == "__main__":
    unittest.main()
