"""ADR-018 §8.4 — DoclingStructuredParser produces drawing-like + handwriting/seal page signals."""

from __future__ import annotations

import unittest

from raku_rag.domain.parsed_document import (
    BLOCK_PARAGRAPH,
    Block,
    Figure,
    Page,
    ParsedDocument,
)
from raku_rag.providers import docling_parser
from raku_rag.providers.docling_parser import DoclingStructuredParser
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


if __name__ == "__main__":
    unittest.main()
