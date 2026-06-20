from __future__ import annotations

import unittest

from raku_rag.services.cost import CostService
from raku_rag.workers.ingestion import VisualIngestionExecutor, VisualIngestionOptions


class TestVisualIngestionExecutor(unittest.TestCase):
    def test_image_ingestion_creates_asset_regions_embeddings_and_visual_costs(self) -> None:
        cost = CostService()
        executor = VisualIngestionExecutor(cost=cost)

        result = executor.execute_image(
            tenant_id="tenant_a",
            collection_id="manuals",
            source_id="upload",
            document_id="doc_visual",
            image=b"OCR: Pump panel shows alarm AL-42.\ncaption: contact alice@example.com for panel",
            exif_metadata={"GPSLatitude": "35.0", "Model": "SensitiveCam", "ColorSpace": "sRGB"},
            job_id="job_visual",
            trace_id="trace_visual",
        )

        self.assertEqual(result.asset.document_id, "doc_visual")
        self.assertEqual(result.asset.metadata["exif"], {"ColorSpace": "sRGB"})
        self.assertEqual(set(result.exif_removed_keys), {"GPSLatitude", "Model"})
        self.assertEqual(result.caption_status, "succeeded")
        self.assertEqual(len(result.regions), 1)
        self.assertEqual(result.regions[0].ocr_text, "Pump panel shows alarm AL-42.")
        self.assertIn("[REDACTED:email]", result.regions[0].generated_caption_text)
        self.assertEqual(len(result.visual_vectors), 1)

        kinds = {record.kind for record in cost.records("tenant_a")}
        self.assertIn("visual_storage_cost", kinds)
        self.assertIn("ocr_cost", kinds)
        self.assertIn("layout_extraction_cost", kinds)
        self.assertIn("captioning_cost", kinds)
        self.assertIn("visual_embedding_cost", kinds)
        self.assertTrue(all(not record.billable for record in cost.records("tenant_a")))

    def test_captioning_disabled_keeps_visual_path_without_caption_cost(self) -> None:
        cost = CostService()
        executor = VisualIngestionExecutor(cost=cost)

        result = executor.execute_image(
            tenant_id="tenant_a",
            collection_id="manuals",
            source_id="upload",
            document_id="doc_visual",
            image=b"OCR: Pump panel shows alarm AL-42.\ncaption: optional caption",
            options=VisualIngestionOptions(captioning_enabled=False),
        )

        self.assertEqual(result.caption_status, "not_requested")
        self.assertEqual(result.regions[0].generated_caption_text, "")
        self.assertEqual(cost.records("tenant_a", kind="captioning_cost"), ())
        self.assertEqual(len(result.visual_vectors), 1)


if __name__ == "__main__":
    unittest.main()
