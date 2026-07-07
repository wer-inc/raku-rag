"""ADR-018 §9.1 — DoclingStructuredParser (Phase B4).

The real-Docling test is skipped where the optional dep is absent (e.g. the stdlib CI gate); the
offline-fallback test runs everywhere and pins the degraded behaviour so an env without Docling never
crashes ingestion.
"""

from __future__ import annotations

import importlib.util
import sys
import types
import unittest

from raku_rag.domain.parsed_document import (
    BLOCK_PARAGRAPH,
    BLOCK_TABLE,
    BLOCK_TITLE,
    PARSED_DOCUMENT_SCHEMA_VERSION,
    Block,
    Page,
    ParsedDocument,
    QualityInfo,
)
from raku_rag.providers import docling_parser
from raku_rag.providers.docling_parser import (
    DoclingStructuredParser,
    _finalize_page_quality,
    _normalize_figures,
    _quality_from_confidence,
    _table_from_item,
    docling_available,
)

_HAS_PYPDFIUM = importlib.util.find_spec("pypdfium2") is not None

_HTML = (
    b"<html><body><h1>Safety Procedure</h1>"
    b"<p>Stop the main power before work.</p>"
    b"<table><tr><th>Item</th><th>Value</th></tr>"
    b"<tr><td>Voltage</td><td>200V</td></tr></table></body></html>"
)


class DoclingSupportTest(unittest.TestCase):
    def test_supports_pdf_and_office_and_images(self) -> None:
        p = DoclingStructuredParser()
        self.assertTrue(p.supports("application/pdf"))
        self.assertTrue(
            p.supports(
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            )
        )
        self.assertTrue(p.supports("text/html"))
        self.assertTrue(p.supports("image/png"))
        self.assertFalse(p.supports("text/csv"))


class DoclingOfflineFallbackTest(unittest.TestCase):
    def setUp(self) -> None:
        self._orig = docling_parser.docling_available
        docling_parser.docling_available = lambda: False

    def tearDown(self) -> None:
        docling_parser.docling_available = self._orig

    def test_fallback_decodes_text_and_records_route_trace(self) -> None:
        doc = DoclingStructuredParser().parse_structured(
            b"line one\n\nline two", "application/pdf", document_id="d1"
        )
        self.assertEqual(doc.schema_version, PARSED_DOCUMENT_SCHEMA_VERSION)
        self.assertEqual([b.text for b in doc.blocks], ["line one", "line two"])
        self.assertEqual(doc.route_trace[0].result, "unavailable")
        self.assertEqual(doc.route_trace[0].reason, "docling_not_installed")
        self.assertEqual(doc.provider_runs[0].provider, "docling")
        self.assertEqual(doc.blocks[0].provenance.route, "docling_unavailable_fallback")

    def test_fallback_is_review_required_not_silently_accepted(self) -> None:
        # §8.4 "provider がすべて失敗" (§P4/§P5) — a raw byte-decode is not a real extraction; it must
        # never read as "accepted" downstream just because the fallback produced plausible-looking text.
        doc = DoclingStructuredParser().parse_structured(
            b"line one\n\nline two", "application/pdf", document_id="d1"
        )
        self.assertEqual(doc.quality.status, "review_required")
        self.assertIn("provider_error", doc.quality.reasons)

    def test_ocr_disable_config_drift_fails_closed(self) -> None:
        created_converters: list[dict] = []

        class _DocumentConverter:
            def __init__(self, *args, **kwargs) -> None:
                created_converters.append(kwargs)

        class _BadPdfPipelineOptions:
            def __init__(self) -> None:
                raise RuntimeError("api drift")

        fake_docling = types.ModuleType("docling")
        fake_docling.__path__ = []
        fake_datamodel = types.ModuleType("docling.datamodel")
        fake_datamodel.__path__ = []
        fake_base = types.ModuleType("docling.datamodel.base_models")
        fake_base.InputFormat = types.SimpleNamespace(PDF="pdf")
        fake_pipeline = types.ModuleType("docling.datamodel.pipeline_options")
        fake_pipeline.PdfPipelineOptions = _BadPdfPipelineOptions
        fake_converter = types.ModuleType("docling.document_converter")
        fake_converter.DocumentConverter = _DocumentConverter
        fake_converter.PdfFormatOption = object

        names = (
            "docling",
            "docling.datamodel",
            "docling.datamodel.base_models",
            "docling.datamodel.pipeline_options",
            "docling.document_converter",
        )
        original = {name: sys.modules.get(name) for name in names}
        try:
            sys.modules.update(
                {
                    "docling": fake_docling,
                    "docling.datamodel": fake_datamodel,
                    "docling.datamodel.base_models": fake_base,
                    "docling.datamodel.pipeline_options": fake_pipeline,
                    "docling.document_converter": fake_converter,
                }
            )
            with self.assertRaisesRegex(RuntimeError, "docling_ocr_disable_config_failed"):
                DoclingStructuredParser()._get_converter()
            self.assertEqual(created_converters, [])
        finally:
            for name, module in original.items():
                if module is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = module


def _minimal_pdf(text: str) -> bytes:
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
    ]
    stream = b"BT /F1 24 Tf 72 700 Td (" + text.encode("latin-1") + b") Tj ET"
    objs.append(
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"
    )
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += str(i).encode() + b" 0 obj\n" + body + b"\nendobj\n"
    xref_pos = len(out)
    out += b"xref\n0 " + str(len(objs) + 1).encode() + b"\n0000000000 65535 f \n"
    for off in offsets:
        out += ("%010d 00000 n \n" % off).encode()
    out += (
        b"trailer\n<< /Size " + str(len(objs) + 1).encode() + b" /Root 1 0 R >>\n"
        b"startxref\n" + str(xref_pos).encode() + b"\n%%EOF"
    )
    return bytes(out)


class PreflightTest(unittest.TestCase):
    @unittest.skipUnless(_HAS_PYPDFIUM, "pypdfium2 not installed")
    def test_preflight_detects_text_layer(self) -> None:
        from raku_rag.providers.docling_parser import preflight_pdf_pages

        signals = preflight_pdf_pages(_minimal_pdf("Hello digital page"))
        self.assertEqual(signals.get(1, {}).get("has_text_layer"), True)
        self.assertEqual(signals.get(1, {}).get("is_scanned"), False)

    def test_preflight_on_garbage_is_empty(self) -> None:
        from raku_rag.providers.docling_parser import preflight_pdf_pages

        self.assertEqual(preflight_pdf_pages(b"not a pdf"), {})


class _FakeConfidence:
    def __init__(self, mean, low, layout) -> None:
        self.mean_score = mean
        self.low_score = low
        self.layout_score = layout


class _FakePicture:
    def __init__(self) -> None:
        self.prov = ()

    def caption_text(self, doc) -> str:
        return "Figure 1: pump assembly"


class _FakeDocWithPicture:
    pictures = (_FakePicture(),)


class DoclingQualityAndFiguresTest(unittest.TestCase):
    def test_quality_from_confidence_builds_dimension_vector(self) -> None:
        q = _quality_from_confidence(_FakeConfidence(0.78, 0.58, 0.55))
        self.assertEqual(q.metrics["ocr_confidence_p50"], 0.78)
        self.assertEqual(q.metrics["ocr_confidence_p10"], 0.58)
        self.assertEqual(q.metrics["layout_confidence"], 0.55)
        self.assertEqual(q.status, "accepted")

    def test_quality_nan_scores_are_dropped(self) -> None:
        q = _quality_from_confidence(_FakeConfidence(float("nan"), float("nan"), float("nan")))
        self.assertEqual(dict(q.metrics), {})

    def test_low_confidence_flags_warnings(self) -> None:
        q = _quality_from_confidence(_FakeConfidence(0.5, 0.1, 0.4))
        self.assertEqual(q.status, "accepted_with_warnings")
        self.assertIn("low_confidence_regions", q.reasons)

    def test_none_confidence_is_plain_accepted(self) -> None:
        self.assertEqual(_quality_from_confidence(None).status, "accepted")

    def test_normalize_figures_captures_pictures(self) -> None:
        from raku_rag.domain.parsed_document import Provenance

        figs = _normalize_figures(_FakeDocWithPicture(), Provenance(provider="docling"))
        self.assertEqual(len(figs), 1)
        self.assertEqual(figs[0].caption, "Figure 1: pump assembly")


class _FakeCell:
    def __init__(
        self,
        *,
        text,
        start_row,
        start_col,
        row_span=1,
        col_span=1,
        column_header=False,
        row_header=False,
        bbox=None,
    ) -> None:
        self.text = text
        self.start_row_offset_idx = start_row
        self.start_col_offset_idx = start_col
        self.row_span = row_span
        self.col_span = col_span
        self.column_header = column_header
        self.row_header = row_header
        self.bbox = bbox


class _FakeTableData:
    def __init__(self, table_cells) -> None:
        self.table_cells = table_cells


class _FakeTableItem:
    def __init__(self, table_cells) -> None:
        self.data = _FakeTableData(table_cells)
        self.prov = ()


class TableFromItemMergedCellsTest(unittest.TestCase):
    """§7.6 — merged cells (rowspan/colspan) via docling's deduplicated ``table_cells`` list."""

    def test_extracts_rowspan_and_colspan_without_duplicating_the_merged_cell(self) -> None:
        item = _FakeTableItem(
            [
                _FakeCell(text="Item", start_row=0, start_col=0, column_header=True),
                _FakeCell(text="Spec", start_row=0, start_col=1, col_span=2, column_header=True),
                _FakeCell(text="Pump", start_row=1, start_col=0),
                _FakeCell(text="Valve", start_row=2, start_col=0, row_span=2),
                _FakeCell(text="Type", start_row=2, start_col=1),
            ]
        )
        table = _table_from_item(item, 0, None)
        self.assertEqual(len(table.cells), 5)  # deduplicated — not repeated at every span position
        by_text = {c.text: c for c in table.cells}
        self.assertEqual(by_text["Spec"].colspan, 2)
        self.assertEqual(by_text["Spec"].rowspan, 1)
        self.assertEqual(by_text["Valve"].rowspan, 2)
        self.assertEqual(by_text["Valve"].colspan, 1)
        self.assertEqual(by_text["Valve"].row, 3)  # 1-indexed
        self.assertEqual(by_text["Valve"].col, 1)
        self.assertTrue(by_text["Item"].is_header)
        self.assertEqual(table.columns[0].text, "Item")

    def test_falls_back_to_grid_when_table_cells_absent(self) -> None:
        class _GridCell:
            def __init__(self, text) -> None:
                self.text = text
                self.column_header = False
                self.row_header = False

        class _GridData:
            table_cells = None
            grid = [[_GridCell("a"), _GridCell("b")]]

        class _GridItem:
            data = _GridData()
            prov = ()

        table = _table_from_item(_GridItem(), 0, None)
        self.assertEqual(len(table.cells), 2)
        self.assertEqual(table.cells[0].rowspan, 1)  # defaults preserved on the fallback path


@unittest.skipUnless(docling_available(), "docling not installed")
class DoclingRealConversionTest(unittest.TestCase):
    def test_html_normalizes_to_parsed_document_with_structure(self) -> None:
        doc = DoclingStructuredParser().parse_structured(
            _HTML, "text/html", document_id="d1", filename="proc.html"
        )
        kinds = [b.kind for b in doc.blocks]
        self.assertIn(BLOCK_TITLE, kinds)
        self.assertIn(BLOCK_PARAGRAPH, kinds)
        self.assertIn(BLOCK_TABLE, kinds)

        # provenance / run recorded (§7.2 / §13.3)
        run = doc.provider_runs[0]
        self.assertEqual(run.provider, "docling")
        self.assertNotEqual(run.provider_version, "")
        self.assertEqual(run.model_versions.get("ocr_provider"), "none")
        # A5 §13.3: real version + config hash + timestamps recorded for reindex/audit.
        self.assertIn(run.provider_version, run.model_versions["layout"])
        self.assertTrue(run.config_hash.startswith("sha256:"))
        self.assertTrue(run.started_at and run.finished_at)

        # §4.2/§9.4: Docling's built-in OCR is disabled and OCR is owned by an independent provider,
        # recorded in the route_trace.
        config_steps = [s for s in doc.route_trace if s.stage == "config"]
        self.assertTrue(config_steps)
        self.assertEqual(config_steps[0].result, "docling_ocr_disabled")
        self.assertEqual(config_steps[0].reason, "external_ocr=none")
        self.assertTrue(any(s.result == "accepted" for s in doc.route_trace))

        # table structure preserved with header detection (§7.6)
        self.assertEqual(len(doc.tables), 1)
        table = doc.tables[0]
        header_cells = {c.text for c in table.cells if c.is_header}
        self.assertEqual(header_cells, {"Item", "Value"})
        body = {(c.text) for c in table.cells if not c.is_header}
        self.assertIn("Voltage", body)
        self.assertIn("200V", body)

        # canonical derived text carries the content
        emb = doc.text_for_embedding()
        self.assertIn("Safety Procedure", emb)
        self.assertIn("Stop the main power before work.", emb)


class FinalizePageQualityTest(unittest.TestCase):
    """§7.3 — each Page gets its own quality verdict, not just the document-level aggregate."""

    def test_clean_page_stays_accepted(self) -> None:
        doc = ParsedDocument(
            blocks=(Block(block_id="b1", kind=BLOCK_PARAGRAPH, text="ok", page_no=1),),
            pages=(Page(page_id="p1", page_no=1),),
        )
        out = _finalize_page_quality(doc)
        self.assertEqual(out.pages[0].quality.status, "accepted")

    def test_page_inherits_worst_block_status(self) -> None:
        doc = ParsedDocument(
            blocks=(
                Block(block_id="b1", kind=BLOCK_PARAGRAPH, text="ok", page_no=1),
                Block(
                    block_id="b2",
                    kind=BLOCK_PARAGRAPH,
                    text="bad",
                    page_no=1,
                    quality=QualityInfo(status="review_required", reasons=("x",)),
                ),
            ),
            pages=(Page(page_id="p1", page_no=1),),
        )
        out = _finalize_page_quality(doc)
        self.assertEqual(out.pages[0].quality.status, "review_required")
        self.assertEqual(out.pages[0].quality.reasons, ("x",))

    def test_page_with_no_blocks_but_a_seal_signal_is_flagged(self) -> None:
        doc = ParsedDocument(
            pages=(Page(page_id="p1", page_no=1, signals={"seal_detected": True}),)
        )
        out = _finalize_page_quality(doc)
        self.assertEqual(out.pages[0].quality.status, "review_required")
        self.assertEqual(out.pages[0].quality.reasons, ("handwriting_or_seal_detected",))

    def test_page_with_no_blocks_and_no_signals_is_accepted(self) -> None:
        doc = ParsedDocument(pages=(Page(page_id="p1", page_no=1),))
        out = _finalize_page_quality(doc)
        self.assertEqual(out.pages[0].quality.status, "accepted")

    def test_no_pages_is_a_no_op(self) -> None:
        doc = ParsedDocument(blocks=(Block(block_id="b1", kind=BLOCK_PARAGRAPH, text="x"),))
        self.assertEqual(_finalize_page_quality(doc).pages, ())


if __name__ == "__main__":
    unittest.main()
