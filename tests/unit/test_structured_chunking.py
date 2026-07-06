"""ADR-018 §11 — structure-aware chunking from ParsedDocument (Phase B3)."""

from __future__ import annotations

import unittest

from raku_rag.domain.parsed_document import (
    ANCHOR_SPREADSHEET_CELL,
    BLOCK_HEADING,
    BLOCK_PARAGRAPH,
    BLOCK_TABLE,
    BLOCK_TITLE,
    Block,
    ParsedDocument,
    QualityInfo,
)
from raku_rag.providers.structured_parsers import SpreadsheetStructuredParser
from raku_rag.services.structured_chunking import (
    CHUNK_CELL,
    CHUNK_PARAGRAPH,
    CHUNK_TABLE,
    chunk_parsed_document,
)


class StructuredChunkingTest(unittest.TestCase):
    def test_heading_becomes_context_not_its_own_chunk(self) -> None:
        doc = ParsedDocument(
            blocks=(
                Block(block_id="t", kind=BLOCK_TITLE, text="Pump Manual", reading_order=0),
                Block(block_id="h", kind=BLOCK_HEADING, text="Maintenance", reading_order=1),
                Block(
                    block_id="p", kind=BLOCK_PARAGRAPH, text="Interval is 90 days.", reading_order=2
                ),
            )
        )
        chunks = chunk_parsed_document(doc)
        self.assertEqual(len(chunks), 1)  # only the paragraph becomes a chunk
        self.assertEqual(chunks[0].kind, CHUNK_PARAGRAPH)
        self.assertEqual(chunks[0].heading_path, ("Pump Manual", "Maintenance"))
        self.assertEqual(chunks[0].source_block_ids, ("p",))

    def test_title_resets_heading_path(self) -> None:
        doc = ParsedDocument(
            blocks=(
                Block(block_id="h0", kind=BLOCK_HEADING, text="Old", reading_order=0),
                Block(block_id="t", kind=BLOCK_TITLE, text="New Doc", reading_order=1),
                Block(block_id="p", kind=BLOCK_PARAGRAPH, text="Body.", reading_order=2),
            )
        )
        chunks = chunk_parsed_document(doc)
        self.assertEqual(chunks[0].heading_path, ("New Doc",))

    def test_table_block_is_one_table_chunk_and_quality_propagates(self) -> None:
        doc = ParsedDocument(
            blocks=(
                Block(
                    block_id="tbl",
                    kind=BLOCK_TABLE,
                    text="| a | b |",
                    reading_order=0,
                    quality=QualityInfo(status="review_required", reasons=("low_table_conf",)),
                ),
            )
        )
        chunks = chunk_parsed_document(doc)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].kind, CHUNK_TABLE)
        self.assertEqual(chunks[0].quality_status, "review_required")
        self.assertEqual(chunks[0].quality_reasons, ("low_table_conf",))

    def test_empty_blocks_skipped(self) -> None:
        doc = ParsedDocument(
            blocks=(
                Block(block_id="e", kind=BLOCK_PARAGRAPH, text="   ", reading_order=0),
                Block(block_id="p", kind=BLOCK_PARAGRAPH, text="real", reading_order=1),
            )
        )
        chunks = chunk_parsed_document(doc)
        self.assertEqual([c.source_block_ids for c in chunks], [("p",)])

    def test_spreadsheet_yields_one_cell_chunk_per_cell_with_anchor(self) -> None:
        csv = b"item,remedy\nP-12,replace valve\nP-13,tighten"
        parsed = SpreadsheetStructuredParser().parse_structured(csv, "text/csv")
        chunks = chunk_parsed_document(parsed)

        self.assertTrue(chunks)
        self.assertTrue(all(c.kind == CHUNK_CELL for c in chunks))
        first = chunks[0]
        self.assertEqual(len(first.source_anchors), 1)
        anchor = first.source_anchors[0]
        self.assertEqual(anchor.type, ANCHOR_SPREADSHEET_CELL)
        self.assertEqual((anchor.sheet, anchor.row, anchor.col), ("sheet1", 2, 1))
        self.assertIn("sheet1!R2C1", first.text_for_embedding)


if __name__ == "__main__":
    unittest.main()
