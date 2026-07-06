"""ADR-018 A7 §8.4 — document-level quality gate over structured confidence signals."""

from __future__ import annotations

import unittest

from raku_rag.domain.parsed_document import (
    BLOCK_PARAGRAPH,
    Block,
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
