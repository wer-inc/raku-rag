"""ADR-018 A7 §8.4 — document-level quality gate over structured confidence signals."""

from __future__ import annotations

import unittest

from raku_rag.domain.parsed_document import (
    BLOCK_PARAGRAPH,
    Block,
    Page,
    ParsedDocument,
    QualityInfo,
    Table,
)
from raku_rag.services.ingestion_quality import (
    QUALITY_STATUS_ACCEPTED,
    QUALITY_STATUS_REVIEW_REQUIRED,
)
from raku_rag.services.structured_chunking import StructuredChunk
from raku_rag.services.structured_ingestion import (
    _chunk_quality_metadata,
    classify_parsed_document_quality,
)


def _doc(metrics: dict, tables=()) -> ParsedDocument:
    return ParsedDocument(
        blocks=(Block(block_id="b", kind=BLOCK_PARAGRAPH, text="x"),),
        tables=tuple(tables),
        quality=QualityInfo(status=QUALITY_STATUS_ACCEPTED, metrics=metrics),
    )


class ClassifyParsedDocumentQualityTest(unittest.TestCase):
    def test_healthy_confidence_is_accepted(self) -> None:
        status, reasons = classify_parsed_document_quality(
            _doc({"overall": 0.8, "layout_confidence": 0.7})
        )
        self.assertEqual(status, QUALITY_STATUS_ACCEPTED)
        self.assertEqual(reasons, ())

    def test_low_overall_confidence_is_review_required(self) -> None:
        status, reasons = classify_parsed_document_quality(_doc({"overall": 0.2}))
        self.assertEqual(status, QUALITY_STATUS_REVIEW_REQUIRED)
        self.assertIn("low_overall_confidence", reasons)

    def test_low_table_structure_confidence_is_review_required(self) -> None:
        table = Table(
            table_id="t", quality=QualityInfo(metrics={"table_structure_confidence": 0.2})
        )
        status, reasons = classify_parsed_document_quality(_doc({"overall": 0.9}, tables=[table]))
        self.assertEqual(status, QUALITY_STATUS_REVIEW_REQUIRED)
        self.assertIn("low_table_structure_confidence", reasons)

    def test_no_metrics_is_accepted(self) -> None:
        status, _ = classify_parsed_document_quality(_doc({}))
        self.assertEqual(status, QUALITY_STATUS_ACCEPTED)

    def test_handwriting_or_seal_page_signal_is_review_required(self) -> None:
        doc = ParsedDocument(
            blocks=(Block(block_id="b", kind=BLOCK_PARAGRAPH, text="x"),),
            pages=(Page(page_id="p1", page_no=1, signals={"seal_detected": True}),),
        )
        status, reasons = classify_parsed_document_quality(doc)
        self.assertEqual(status, QUALITY_STATUS_REVIEW_REQUIRED)
        self.assertIn("handwriting_or_seal_detected", reasons)

    def test_drawing_only_page_signal_is_review_required(self) -> None:
        doc = ParsedDocument(
            blocks=(Block(block_id="b", kind=BLOCK_PARAGRAPH, text="x"),),
            pages=(Page(page_id="p1", page_no=1, signals={"drawing_like": True}),),
        )
        status, reasons = classify_parsed_document_quality(doc)
        self.assertEqual(status, QUALITY_STATUS_REVIEW_REQUIRED)
        self.assertIn("drawing_only_page", reasons)

    def test_language_mismatch_is_review_required_only_when_expected_language_set(self) -> None:
        corrupt = "Pmp P-12 mntnc ntrvl nnty dys fr th mchn nt xyzq abcd efgh ijkl mnop"
        doc = ParsedDocument(blocks=(Block(block_id="b", kind=BLOCK_PARAGRAPH, text=corrupt),))
        # no expected language => not judged
        self.assertEqual(classify_parsed_document_quality(doc)[0], QUALITY_STATUS_ACCEPTED)
        # expected ja but de-japanized => review
        status, reasons = classify_parsed_document_quality(doc, expected_language="ja")
        self.assertEqual(status, QUALITY_STATUS_REVIEW_REQUIRED)
        self.assertIn("language_mismatch", reasons)


class AdditionalDimensionGatesTest(unittest.TestCase):
    """§8.4 gates over dimensions that were previously computed but not enforced."""

    def test_low_ocr_confidence_p10_is_review_required(self) -> None:
        status, reasons = classify_parsed_document_quality(
            _doc({"overall": 0.8, "ocr_confidence_p10": 0.1})
        )
        self.assertEqual(status, QUALITY_STATUS_REVIEW_REQUIRED)
        self.assertIn("low_ocr_confidence_p10", reasons)

    def test_healthy_ocr_confidence_p10_is_accepted(self) -> None:
        status, _ = classify_parsed_document_quality(
            _doc({"overall": 0.8, "ocr_confidence_p10": 0.9})
        )
        self.assertEqual(status, QUALITY_STATUS_ACCEPTED)

    def test_high_empty_page_risk_is_review_required(self) -> None:
        status, reasons = classify_parsed_document_quality(
            _doc({"overall": 0.8, "empty_page_risk": 0.5})
        )
        self.assertEqual(status, QUALITY_STATUS_REVIEW_REQUIRED)
        self.assertIn("high_empty_page_risk", reasons)

    def test_high_reading_order_risk_is_review_required(self) -> None:
        status, reasons = classify_parsed_document_quality(
            _doc({"overall": 0.8, "reading_order_risk": 0.6})
        )
        self.assertEqual(status, QUALITY_STATUS_REVIEW_REQUIRED)
        self.assertIn("high_reading_order_risk", reasons)

    def test_provider_error_dimension_is_review_required(self) -> None:
        status, reasons = classify_parsed_document_quality(
            _doc({"overall": 0.8, "provider_error": 1.0})
        )
        self.assertEqual(status, QUALITY_STATUS_REVIEW_REQUIRED)
        self.assertIn("provider_error", reasons)


class ChunkQualityFloorTest(unittest.TestCase):
    def _chunk(self) -> StructuredChunk:
        return StructuredChunk(
            text_for_embedding="Pump P-12 interval ninety days.",
            display_text="Pump P-12 interval ninety days.",
            kind="paragraph_chunk",
        )

    def test_document_floor_forces_review_on_otherwise_clean_chunk(self) -> None:
        meta = _chunk_quality_metadata(
            self._chunk(),
            doc_floor_status=QUALITY_STATUS_REVIEW_REQUIRED,
            doc_floor_reasons=("low_overall_confidence",),
        )
        self.assertEqual(meta["extraction_quality_status"], QUALITY_STATUS_REVIEW_REQUIRED)
        self.assertIn("low_overall_confidence", meta["extraction_quality_reasons"])

    def test_clean_chunk_without_floor_stays_accepted(self) -> None:
        meta = _chunk_quality_metadata(self._chunk())
        self.assertEqual(meta["extraction_quality_status"], QUALITY_STATUS_ACCEPTED)


if __name__ == "__main__":
    unittest.main()
