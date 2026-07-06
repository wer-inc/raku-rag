"""ADR-018 §8.4 — DoclingStructuredParser produces drawing-like + handwriting/seal page signals."""

from __future__ import annotations

import unittest

from raku_rag.domain.parsed_document import (
    BLOCK_PARAGRAPH,
    Block,
    Figure,
    Page,
    ParsedDocument,
    Table,
)
from raku_rag.providers import docling_parser
from raku_rag.providers.docling_parser import DoclingStructuredParser
from raku_rag.providers.page_routing import (
    PAGE_DIGITAL_MOJIBAKE,
    PAGE_TABLE_HEAVY,
    classify_page_route,
)
from raku_rag.services.quality_detectors import (
    CallableVisualArtifactDetector,
    VisualArtifactSignals,
)


class ApplyVisualDetectorsTest(unittest.TestCase):
    def _doc(self, *, text: str, with_figure: bool) -> ParsedDocument:
        return ParsedDocument(
            blocks=(Block(block_id="b", kind=BLOCK_PARAGRAPH, text=text, page_no=1),),
            figures=(Figure(figure_id="f", page_no=1),) if with_figure else (),
            pages=(Page(page_id="p1", page_no=1),),
        )

    def test_figure_page_with_no_text_is_flagged_drawing_like(self) -> None:
        parser = DoclingStructuredParser()
        out = parser._apply_visual_detectors(
            self._doc(text="", with_figure=True), b"", "application/pdf"
        )
        self.assertTrue(dict(out.pages[0].signals).get("drawing_like"))

    def test_text_page_is_not_drawing_like(self) -> None:
        parser = DoclingStructuredParser()
        out = parser._apply_visual_detectors(
            self._doc(text="A long paragraph of real text " * 5, with_figure=True),
            b"",
            "application/pdf",
        )
        self.assertFalse(dict(out.pages[0].signals).get("drawing_like"))

    def test_vision_detector_populates_handwriting_seal(self) -> None:
        detector = CallableVisualArtifactDetector(
            lambda img, page: VisualArtifactSignals(handwriting_detected=True, seal_detected=True)
        )
        parser = DoclingStructuredParser(visual_artifact_detector=detector)
        # detector path renders the PDF page; stub the renderer so no pypdfium2 dep is needed.
        orig = docling_parser.render_pdf_page_png
        docling_parser.render_pdf_page_png = lambda raw, page_no: b"PNGBYTES"
        try:
            out = parser._apply_visual_detectors(
                self._doc(text="some text", with_figure=False), b"%PDF", "application/pdf"
            )
        finally:
            docling_parser.render_pdf_page_png = orig
        signals = dict(out.pages[0].signals)
        self.assertTrue(signals.get("handwriting_detected"))
        self.assertTrue(signals.get("seal_detected"))

    def test_noop_detector_and_no_figures_leaves_signals_untouched(self) -> None:
        parser = DoclingStructuredParser()  # default NoOp detector
        out = parser._apply_visual_detectors(
            self._doc(text="plain text", with_figure=False), b"", "application/pdf"
        )
        self.assertEqual(dict(out.pages[0].signals), {})

    def test_standalone_image_upload_also_runs_the_vision_detector(self) -> None:
        # §8.4 — a standalone photo/scan (写真・画像化された文書) IS a single-page document; the
        # detector must run on it too, not just PDF pages.
        detector = CallableVisualArtifactDetector(
            lambda img, page: VisualArtifactSignals(seal_detected=True)
        )
        parser = DoclingStructuredParser(visual_artifact_detector=detector)
        orig = docling_parser._standalone_image_to_png
        docling_parser._standalone_image_to_png = lambda raw: b"PNGBYTES"
        try:
            out = parser._apply_visual_detectors(
                self._doc(text="some text", with_figure=False), b"\x89PNG", "image/png"
            )
        finally:
            docling_parser._standalone_image_to_png = orig
        self.assertTrue(dict(out.pages[0].signals).get("seal_detected"))

    def test_table_page_is_flagged_table_heavy_and_routes_accordingly(self) -> None:
        # §6.2 — without this signal, PAGE_TABLE_HEAVY could never be selected by page_routing.
        doc = ParsedDocument(
            blocks=(Block(block_id="b", kind=BLOCK_PARAGRAPH, text="x", page_no=1),),
            tables=(Table(table_id="t1", page_no=1),),
            pages=(Page(page_id="p1", page_no=1),),
        )
        out = DoclingStructuredParser()._apply_visual_detectors(doc, b"", "application/pdf")
        self.assertTrue(dict(out.pages[0].signals).get("table_heavy"))
        self.assertEqual(classify_page_route(out.pages[0].signals).page_type, PAGE_TABLE_HEAVY)

    def test_mojibake_heavy_page_is_flagged_and_routes_accordingly(self) -> None:
        # §6.2 — without this signal, PAGE_DIGITAL_MOJIBAKE could never be selected by page_routing.
        doc = ParsedDocument(
            blocks=(
                Block(block_id="b", kind=BLOCK_PARAGRAPH, text="garbled " + "�" * 20, page_no=1),
            ),
            pages=(Page(page_id="p1", page_no=1),),
        )
        out = DoclingStructuredParser()._apply_visual_detectors(doc, b"", "application/pdf")
        self.assertTrue(dict(out.pages[0].signals).get("mojibake_suspected"))
        self.assertEqual(classify_page_route(out.pages[0].signals).page_type, PAGE_DIGITAL_MOJIBAKE)

    def test_clean_page_is_not_flagged_table_heavy_or_mojibake(self) -> None:
        out = DoclingStructuredParser()._apply_visual_detectors(
            self._doc(text="clean readable text here", with_figure=True), b"", "application/pdf"
        )
        signals = dict(out.pages[0].signals)
        self.assertNotIn("table_heavy", signals)
        self.assertNotIn("mojibake_suspected", signals)

    def test_pdf_only_gate_no_longer_excludes_jpeg_or_tiff(self) -> None:
        detector = CallableVisualArtifactDetector(
            lambda img, page: VisualArtifactSignals(handwriting_detected=True)
        )
        for content_type in ("image/jpeg", "image/tiff"):
            parser = DoclingStructuredParser(visual_artifact_detector=detector)
            orig = docling_parser._standalone_image_to_png
            docling_parser._standalone_image_to_png = lambda raw: b"PNGBYTES"
            try:
                out = parser._apply_visual_detectors(
                    self._doc(text="some text", with_figure=False), b"raw", content_type
                )
            finally:
                docling_parser._standalone_image_to_png = orig
            self.assertTrue(dict(out.pages[0].signals).get("handwriting_detected"), content_type)


if __name__ == "__main__":
    unittest.main()
