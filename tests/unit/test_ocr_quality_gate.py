"""★V1 取込品質ゲート — per-region OCR confidences roll up to a document-level review flag."""

from __future__ import annotations

import os
import unittest

from raku_rag.domain.models import BoundingBox, LayoutRegion, VisualAsset
from raku_rag.services.ingestion_quality import (
    EXTRACTION_QUALITY_STATUS_KEY,
    QUALITY_STATUS_ACCEPTED,
    QUALITY_STATUS_REVIEW_REQUIRED,
    is_retrieval_eligible,
    quality_metadata_from_ocr_metadata,
)
from raku_rag.workers.ingestion import (
    VisualIngestionResult,
    _ocr_quality_metadata,
)

T = "tenant_a"


def _region(confidence: float | None, *, aggregate: bool = False) -> LayoutRegion:
    return LayoutRegion(
        tenant_id=T,
        collection_id="c",
        document_id="d1",
        asset_id="a1",
        region_id=f"r{confidence}",
        bbox=BoundingBox(0.0, 0.0, 1.0, 1.0),
        page_number=1,
        region_type="page" if aggregate else "line",
        heading_path=("visual",),
        ocr_text="text",
        transcription_confidence=confidence,
        metadata={"page_aggregate": True} if aggregate else {},
    )


def _result(*regions: LayoutRegion) -> VisualIngestionResult:
    return VisualIngestionResult(
        asset=VisualAsset(
            tenant_id=T,
            collection_id="c",
            document_id="d1",
            asset_id="a1",
            storage_uri="mem://a1",
            content_type="image/png",
            checksum="x",
        ),
        regions=tuple(regions),
        visual_vectors=(),
        caption_status="succeeded",
    )


class OcrQualityGateTest(unittest.TestCase):
    def tearDown(self) -> None:
        os.environ.pop("RAKU_OCR_CONFIDENCE_REVIEW_THRESHOLD", None)

    def test_low_confidence_flags_review(self) -> None:
        meta = _ocr_quality_metadata((_result(_region(97.0), _region(72.5)),))
        self.assertEqual(meta["ocr_confidence_min"], 72.5)
        self.assertAlmostEqual(meta["ocr_confidence_mean"], 84.75)
        self.assertTrue(meta["ocr_quality_review_required"])
        quality = quality_metadata_from_ocr_metadata(meta)
        self.assertEqual(quality[EXTRACTION_QUALITY_STATUS_KEY], QUALITY_STATUS_REVIEW_REQUIRED)
        self.assertFalse(is_retrieval_eligible(quality))

    def test_high_confidence_passes(self) -> None:
        meta = _ocr_quality_metadata((_result(_region(97.0), _region(94.0)),))
        self.assertFalse(meta["ocr_quality_review_required"])
        quality = quality_metadata_from_ocr_metadata(meta)
        self.assertEqual(quality[EXTRACTION_QUALITY_STATUS_KEY], QUALITY_STATUS_ACCEPTED)
        self.assertTrue(is_retrieval_eligible(quality))

    def test_threshold_is_configurable(self) -> None:
        os.environ["RAKU_OCR_CONFIDENCE_REVIEW_THRESHOLD"] = "95"
        meta = _ocr_quality_metadata((_result(_region(94.0)),))
        self.assertTrue(meta["ocr_quality_review_required"])
        self.assertEqual(meta["ocr_quality_review_threshold"], 95.0)

    def test_page_aggregates_do_not_double_count(self) -> None:
        meta = _ocr_quality_metadata((_result(_region(96.0), _region(50.0, aggregate=True)),))
        self.assertEqual(meta["ocr_confidence_min"], 96.0)
        self.assertFalse(meta["ocr_quality_review_required"])

    def test_no_confidences_yields_no_verdict(self) -> None:
        self.assertEqual(_ocr_quality_metadata((_result(_region(None)),)), {})


if __name__ == "__main__":
    unittest.main()
