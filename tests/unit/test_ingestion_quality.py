"""ADR 018 extraction-quality metadata contract."""

from __future__ import annotations

import unittest

from raku_rag.domain.models import Chunk, Modality
from raku_rag.services.ingestion_quality import (
    EXTRACTION_QUALITY_SCHEMA_VERSION,
    EXTRACTION_QUALITY_SCHEMA_VERSION_KEY,
    EXTRACTION_QUALITY_STATUS_KEY,
    HIGH_RISK_CITATION_ELIGIBLE_KEY,
    QUALITY_STATUS_ACCEPTED,
    QUALITY_STATUS_ACCEPTED_WITH_WARNINGS,
    QUALITY_STATUS_DRAFT_VISUAL,
    QUALITY_STATUS_REVIEW_REQUIRED,
    REASON_CID_ARTIFACTS,
    REASON_EMPTY_EXTRACTION,
    REASON_MINOR_MOJIBAKE,
    REASON_MOJIBAKE_SUSPECTED,
    RETRIEVAL_ELIGIBLE_KEY,
    accepted_quality_metadata,
    accepted_with_warnings_quality_metadata,
    classify_text_extraction_quality,
    extraction_review_items,
    is_high_risk_citation_quality_eligible,
    is_retrieval_eligible,
    quality_metadata_from_ocr_metadata,
    review_required_quality_metadata,
)


class IngestionQualityMetadataTest(unittest.TestCase):
    def test_accepted_metadata_is_retrieval_and_citation_eligible(self) -> None:
        metadata = accepted_quality_metadata()

        self.assertEqual(
            metadata[EXTRACTION_QUALITY_SCHEMA_VERSION_KEY], EXTRACTION_QUALITY_SCHEMA_VERSION
        )
        self.assertEqual(metadata[EXTRACTION_QUALITY_STATUS_KEY], QUALITY_STATUS_ACCEPTED)
        self.assertTrue(metadata[RETRIEVAL_ELIGIBLE_KEY])
        self.assertTrue(metadata[HIGH_RISK_CITATION_ELIGIBLE_KEY])
        self.assertTrue(is_retrieval_eligible(metadata))
        self.assertTrue(is_high_risk_citation_quality_eligible(metadata))

    def test_review_required_metadata_is_not_retrievable(self) -> None:
        metadata = review_required_quality_metadata(reasons=("low_ocr_confidence",))

        self.assertEqual(metadata[EXTRACTION_QUALITY_STATUS_KEY], QUALITY_STATUS_REVIEW_REQUIRED)
        self.assertFalse(metadata[RETRIEVAL_ELIGIBLE_KEY])
        self.assertFalse(metadata[HIGH_RISK_CITATION_ELIGIBLE_KEY])
        self.assertFalse(is_retrieval_eligible(metadata))
        self.assertFalse(is_high_risk_citation_quality_eligible(metadata))

    def test_explicit_retrieval_false_wins_over_missing_status(self) -> None:
        self.assertFalse(is_retrieval_eligible({RETRIEVAL_ELIGIBLE_KEY: "false"}))

    def test_low_ocr_quality_maps_to_review_required(self) -> None:
        metadata = quality_metadata_from_ocr_metadata({"ocr_quality_review_required": True})

        self.assertEqual(metadata[EXTRACTION_QUALITY_STATUS_KEY], QUALITY_STATUS_REVIEW_REQUIRED)
        self.assertFalse(is_retrieval_eligible(metadata))

    def test_accepted_with_warnings_is_retrievable_but_not_high_risk(self) -> None:
        metadata = accepted_with_warnings_quality_metadata(reasons=(REASON_MINOR_MOJIBAKE,))

        self.assertEqual(
            metadata[EXTRACTION_QUALITY_STATUS_KEY], QUALITY_STATUS_ACCEPTED_WITH_WARNINGS
        )
        self.assertTrue(is_retrieval_eligible(metadata))
        self.assertFalse(is_high_risk_citation_quality_eligible(metadata))


class ClassifyTextExtractionQualityTest(unittest.TestCase):
    def test_clean_text_is_accepted(self) -> None:
        metadata = classify_text_extraction_quality("作業前に主電源を停止すること。", raw_size=64)
        self.assertEqual(metadata[EXTRACTION_QUALITY_STATUS_KEY], QUALITY_STATUS_ACCEPTED)
        self.assertTrue(is_retrieval_eligible(metadata))

    def test_empty_yield_on_nontrivial_input_is_review_required(self) -> None:
        metadata = classify_text_extraction_quality("   ", raw_size=4096)
        self.assertEqual(metadata[EXTRACTION_QUALITY_STATUS_KEY], QUALITY_STATUS_REVIEW_REQUIRED)
        self.assertIn(REASON_EMPTY_EXTRACTION, metadata["extraction_quality_reasons"])

    def test_empty_yield_on_empty_input_is_accepted(self) -> None:
        # An genuinely empty/short source is not a broken extraction.
        metadata = classify_text_extraction_quality("", raw_size=10)
        self.assertEqual(metadata[EXTRACTION_QUALITY_STATUS_KEY], QUALITY_STATUS_ACCEPTED)

    def test_cid_artifacts_are_review_required(self) -> None:
        metadata = classify_text_extraction_quality("(cid:12)(cid:34) 手順", raw_size=64)
        self.assertEqual(metadata[EXTRACTION_QUALITY_STATUS_KEY], QUALITY_STATUS_REVIEW_REQUIRED)
        self.assertIn(REASON_CID_ARTIFACTS, metadata["extraction_quality_reasons"])

    def test_heavy_mojibake_is_review_required(self) -> None:
        metadata = classify_text_extraction_quality("正常" + "�" * 20, raw_size=64)
        self.assertEqual(metadata[EXTRACTION_QUALITY_STATUS_KEY], QUALITY_STATUS_REVIEW_REQUIRED)
        self.assertIn(REASON_MOJIBAKE_SUSPECTED, metadata["extraction_quality_reasons"])

    def test_trace_mojibake_is_accepted_with_warnings(self) -> None:
        clean = "作業標準書の手順です。" * 20
        metadata = classify_text_extraction_quality(clean + "�", raw_size=1024)
        self.assertEqual(
            metadata[EXTRACTION_QUALITY_STATUS_KEY], QUALITY_STATUS_ACCEPTED_WITH_WARNINGS
        )
        self.assertTrue(is_retrieval_eligible(metadata))
        self.assertFalse(is_high_risk_citation_quality_eligible(metadata))


class ExtractionReviewQueueTest(unittest.TestCase):
    def _chunk(self, chunk_id: str, quality: dict) -> Chunk:
        return Chunk(
            tenant_id="t",
            chunk_id=chunk_id,
            document_id=chunk_id.split(":")[0],
            collection_id="c",
            text="x",
            position=0,
            token_count=1,
            heading_path=(),
            modality=Modality.TEXT,
            embedding_model_version="v",
            metadata=quality,
        )

    def test_only_quarantined_chunks_surface_in_the_queue(self) -> None:
        items = [
            (self._chunk("acc:0", accepted_quality_metadata()), None),
            (
                self._chunk(
                    "rev:0", review_required_quality_metadata(reasons=("low_ocr_confidence",))
                ),
                None,
            ),
            (
                self._chunk(
                    "vis:0",
                    review_required_quality_metadata(status=QUALITY_STATUS_DRAFT_VISUAL),
                ),
                None,
            ),
            (self._chunk("warn:0", accepted_with_warnings_quality_metadata()), None),
        ]

        queue = extraction_review_items(items)
        surfaced = {(item.document_id, item.status) for item in queue}
        self.assertEqual(
            surfaced,
            {("rev", QUALITY_STATUS_REVIEW_REQUIRED), ("vis", QUALITY_STATUS_DRAFT_VISUAL)},
        )
        review = next(item for item in queue if item.document_id == "rev")
        self.assertIn("low_ocr_confidence", review.reasons)

    def test_tenant_filter(self) -> None:
        chunk = self._chunk("rev:0", review_required_quality_metadata())
        self.assertEqual(len(extraction_review_items([chunk], tenant_id="t")), 1)
        self.assertEqual(len(extraction_review_items([chunk], tenant_id="other")), 0)

    def test_extraction_review_queue_prefers_efficient_store_method(self) -> None:
        from raku_rag.services.ingestion_quality import extraction_review_queue

        rev = self._chunk("rev:0", review_required_quality_metadata(reasons=("x",)))

        class _EfficientStore:
            def list_extraction_review_chunks(self):
                return (rev,)

            def iter_items(self):  # must NOT be used when the efficient method exists
                raise AssertionError("iter_items should not be called")

        q = extraction_review_queue(_EfficientStore(), tenant_id="t")
        self.assertEqual([it.document_id for it in q], ["rev"])

    def test_extraction_review_queue_falls_back_to_iter_items(self) -> None:
        from raku_rag.services.ingestion_quality import extraction_review_queue

        rev = self._chunk("rev:0", review_required_quality_metadata())
        acc = self._chunk("acc:0", accepted_quality_metadata())

        class _InMemStore:
            def iter_items(self):
                return ((acc, None), (rev, None))

        q = extraction_review_queue(_InMemStore())
        self.assertEqual([it.document_id for it in q], ["rev"])


if __name__ == "__main__":
    unittest.main()
