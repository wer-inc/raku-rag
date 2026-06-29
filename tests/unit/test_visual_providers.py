from __future__ import annotations

import unittest

from raku_rag.domain.models import (
    BoundingBox,
    CaptionSource,
    ExtractionSource,
    LayoutRegion,
    VisualAsset,
)
from raku_rag.providers.captioning import DeterministicCaptioningProvider
from raku_rag.providers.layout import DeterministicLayoutExtractor
from raku_rag.providers.ocr import DeterministicOcrEngine
from raku_rag.providers.visual_embeddings import HashingVisualEmbeddingProvider
from raku_rag.providers.vlms import ExtractiveVLMProvider
from raku_rag.services.visual import visual_chunks_from_ingestion
from raku_rag.workers.ingestion import VisualIngestionResult


class TestVisualProviders(unittest.TestCase):
    def test_ocr_and_layout_extract_traceable_regions(self) -> None:
        image = b"OCR: Motor alarm AL-42 is shown on panel P1.\ncaption: operator panel"
        ocr = DeterministicOcrEngine()
        layout = DeterministicLayoutExtractor(ocr)

        ocr_regions = ocr.extract(image)
        regions = layout.extract(
            image,
            tenant_id="tenant_a",
            collection_id="manuals",
            document_id="doc_visual",
            asset_id="asset_1",
            ocr_regions=ocr_regions,
        )

        self.assertEqual(len(ocr_regions), 1)
        self.assertEqual(ocr_regions[0].text, "Motor alarm AL-42 is shown on panel P1.")
        self.assertEqual(regions[0].region_id, "asset_1:region:1")
        self.assertEqual(regions[0].ocr_text, ocr_regions[0].text)
        self.assertEqual(regions[0].heading_path, ("visual",))

    def test_captioning_is_optional_and_redacted(self) -> None:
        provider = DeterministicCaptioningProvider()
        disabled = DeterministicCaptioningProvider(enabled=False)
        failed = DeterministicCaptioningProvider(fail=True)

        result = provider.caption(b"caption: contact alice@example.com near the machine")

        self.assertEqual(result.status, "succeeded")
        self.assertNotIn("alice@example.com", result.generated_caption_text)
        self.assertIn("[REDACTED:email]", result.generated_caption_text)
        self.assertEqual(disabled.caption(b"caption: panel").status, "not_requested")
        self.assertEqual(failed.caption(b"caption: panel").status, "failed")

    def test_visual_embeddings_are_deterministic_normalized_vectors(self) -> None:
        provider = HashingVisualEmbeddingProvider(dim=32)

        a = provider.embed([b"pump alarm panel"])[0]
        b = provider.embed([b"pump alarm panel"])[0]
        c = provider.embed([b"safety manual lockout"])[0]

        self.assertEqual(a, b)
        self.assertNotEqual(a, c)
        self.assertEqual(len(a), 32)
        self.assertAlmostEqual(sum(v * v for v in a), 1.0)

    def test_vlm_uses_ocr_region_text_not_generated_caption_as_primary_evidence(self) -> None:
        vlm = ExtractiveVLMProvider()
        caption_only = LayoutRegion(
            tenant_id="tenant_a",
            collection_id="manuals",
            document_id="doc_visual",
            asset_id="asset_1",
            region_id="asset_1:region:1",
            bbox=BoundingBox(0.0, 0.0, 1.0, 1.0),
            generated_caption_text="The panel shows alarm AL-42.",
        )
        ocr_backed = LayoutRegion(
            tenant_id="tenant_a",
            collection_id="manuals",
            document_id="doc_visual",
            asset_id="asset_1",
            region_id="asset_1:region:2",
            bbox=BoundingBox(0.0, 0.0, 1.0, 1.0),
            ocr_text="The panel shows alarm AL-42.",
        )

        self.assertEqual(vlm.generate("what alarm is shown?", visual_regions=[caption_only]), "")
        self.assertIn("AL-42", vlm.generate("what alarm is shown?", visual_regions=[ocr_backed]))

    def test_visual_chunks_preserve_disjoint_primary_and_caption_sources(self) -> None:
        region = LayoutRegion(
            tenant_id="tenant_a",
            collection_id="manuals",
            document_id="doc_visual",
            asset_id="asset_1",
            region_id="asset_1:region:1",
            bbox=BoundingBox(0.0, 0.0, 1.0, 1.0),
            ocr_text="The panel shows alarm AL-42.",
            generated_caption_text="A model caption about the panel.",
            extraction_source=ExtractionSource.DETERMINISTIC_OCR.value,
            caption_source=CaptionSource.DETERMINISTIC_CAPTION.value,
        )
        result = VisualIngestionResult(
            asset=VisualAsset(
                tenant_id="tenant_a",
                collection_id="manuals",
                document_id="doc_visual",
                asset_id="asset_1",
                storage_uri="memory://asset",
                checksum="checksum",
            ),
            regions=(region,),
            visual_vectors=((0.0,),),
            caption_status="succeeded",
        )

        chunk = visual_chunks_from_ingestion(result)[0]

        self.assertEqual(
            chunk.metadata["primary_evidence_source"],
            ExtractionSource.DETERMINISTIC_OCR.value,
        )
        self.assertEqual(
            chunk.metadata["caption_source"],
            CaptionSource.DETERMINISTIC_CAPTION.value,
        )
        self.assertEqual(chunk.metadata["primary_evidence_text"], region.ocr_text)


if __name__ == "__main__":
    unittest.main()
