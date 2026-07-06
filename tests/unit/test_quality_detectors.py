"""ADR-018 §8.3/§8.4 quality detectors."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from raku_rag.services.quality_detectors import (
    CallableVisualArtifactDetector,
    NoOpVisualArtifactDetector,
    VisualArtifactSignals,
    is_drawing_like,
    is_language_mismatch,
    is_vertical_text_suspected,
    japanese_char_ratio,
    select_visual_artifact_detector,
    table_structure_confidence,
)


def _cell(row, col, text="", header=False):
    return SimpleNamespace(row=row, col=col, text=text, is_header=header)


class TableStructureConfidenceTest(unittest.TestCase):
    def test_clean_table_is_high(self) -> None:
        cells = [_cell(r, c, "x", header=(r == 1)) for r in (1, 2) for c in (1, 2)]
        self.assertGreaterEqual(table_structure_confidence(cells), 0.9)

    def test_no_cells_is_zero(self) -> None:
        self.assertEqual(table_structure_confidence([]), 0.0)

    def test_detected_grid_with_unreadable_cells_is_low(self) -> None:
        cells = [_cell(r, c, "", header=False) for r in (1, 2) for c in (1, 2)]
        self.assertLess(table_structure_confidence(cells), 0.40)


class LanguageConsistencyTest(unittest.TestCase):
    def test_japanese_ratio(self) -> None:
        self.assertGreater(japanese_char_ratio("ポンプの点検を実施する"), 0.9)
        self.assertEqual(japanese_char_ratio("pump inspection"), 0.0)

    def test_expected_ja_but_de_japanized_is_mismatch(self) -> None:
        corrupt = "Pmp P-12 mntnc ntrvl nnty dys fr th mchn nt xyzq abcd efgh ijkl"
        self.assertTrue(is_language_mismatch(corrupt, "ja"))

    def test_real_japanese_is_not_mismatch(self) -> None:
        ok = "ポンプP-12の点検は九十日ごとに実施し、主電源を遮断してから作業を開始する装置番号"
        self.assertFalse(is_language_mismatch(ok, "ja"))

    def test_no_expected_language_never_fires(self) -> None:
        self.assertFalse(is_language_mismatch("all latin text here for the unit no jp at all", ""))

    def test_short_text_is_not_judged(self) -> None:
        self.assertFalse(is_language_mismatch("short latin", "ja"))


class DrawingLikeTest(unittest.TestCase):
    def test_figures_with_no_text_is_drawing_like(self) -> None:
        self.assertTrue(is_drawing_like(has_figures=True, text_char_count=3))

    def test_text_page_is_not_drawing_like(self) -> None:
        self.assertFalse(is_drawing_like(has_figures=True, text_char_count=400))
        self.assertFalse(is_drawing_like(has_figures=False, text_char_count=0))


class VerticalTextTest(unittest.TestCase):
    def test_many_one_char_japanese_lines_is_suspected(self) -> None:
        self.assertTrue(is_vertical_text_suspected("\n".join("点検手順書項目一覧")))

    def test_normal_japanese_prose_is_not_suspected(self) -> None:
        self.assertFalse(
            is_vertical_text_suspected(
                "ポンプP-12の点検は90日ごとに実施し、主電源を遮断してから作業を開始する。次に安全弁を確認する。"
            )
        )

    def test_english_short_lines_are_not_suspected(self) -> None:
        # The Japanese-majority guard keeps English bullet lists from tripping the heuristic.
        self.assertFalse(is_vertical_text_suspected("\n".join(["a", "b", "c", "d", "e", "f", "g"])))

    def test_too_few_lines_is_not_judged(self) -> None:
        self.assertFalse(is_vertical_text_suspected("点\n検\n手"))


class DocumentQualityDimensionsTest(unittest.TestCase):
    def _parsed(self):
        from raku_rag.domain.parsed_document import (
            BLOCK_PARAGRAPH,
            Block,
            Figure,
            Page,
            ParsedDocument,
            QualityInfo,
            RouteTraceStep,
            Table,
            TableCell,
        )

        return ParsedDocument(
            blocks=(
                Block(
                    block_id="b1",
                    kind=BLOCK_PARAGRAPH,
                    text="clean text",
                    page_no=1,
                    reading_order=0,
                ),
                Block(
                    block_id="b2",
                    kind=BLOCK_PARAGRAPH,
                    text="more text",
                    page_no=1,
                    reading_order=1,
                ),
            ),
            tables=(
                Table(
                    table_id="t",
                    cells=(TableCell(row=1, col=1, text="a"),),
                    quality=QualityInfo(metrics={"table_structure_confidence": 0.8}),
                ),
            ),
            figures=(Figure(figure_id="f", page_no=2, caption="Fig 1"),),
            pages=(
                Page(page_id="p1", page_no=1),
                Page(page_id="p2", page_no=2, signals={"drawing_like": True}),
            ),
            route_trace=(RouteTraceStep(stage="extract", result="accepted"),),
        )

    def test_dimensions_are_populated(self):
        from raku_rag.services.quality_detectors import document_quality_dimensions

        dims = document_quality_dimensions(self._parsed())
        self.assertEqual(dims["mojibake_risk"], 0.0)
        self.assertEqual(dims["reading_order_risk"], 0.0)
        self.assertEqual(dims["text_yield"], 0.5)  # page 1 has text, page 2 (figure) does not
        self.assertEqual(dims["empty_page_risk"], 0.5)
        self.assertEqual(dims["drawing_like"], 1.0)
        self.assertEqual(dims["visual_coverage"], 1.0)  # the one figure has a caption
        self.assertIn("vertical_text_suspected", dims)  # §8.3 dimension is always present
        self.assertEqual(dims["cell_anchor_coverage"], 1.0)
        self.assertEqual(dims["table_structure_confidence"], 0.8)
        self.assertEqual(dims["provider_error"], 0.0)

    def test_provider_error_flagged_on_unavailable_route(self):
        from raku_rag.domain.parsed_document import ParsedDocument, RouteTraceStep
        from raku_rag.services.quality_detectors import document_quality_dimensions

        parsed = ParsedDocument(route_trace=(RouteTraceStep(stage="config", result="unavailable"),))
        self.assertEqual(document_quality_dimensions(parsed)["provider_error"], 1.0)


class VisualArtifactDetectorTest(unittest.TestCase):
    def test_default_is_noop_and_unavailable(self) -> None:
        det = select_visual_artifact_detector()
        self.assertIsInstance(det, NoOpVisualArtifactDetector)
        self.assertFalse(det.available())
        self.assertFalse(det.detect(b"x", page_no=1).any())

    def test_callable_detector_reports_signals(self) -> None:
        det = CallableVisualArtifactDetector(
            lambda img, page: VisualArtifactSignals(handwriting_detected=True)
        )
        self.assertTrue(det.available())
        self.assertTrue(det.detect(b"x", page_no=1).handwriting_detected)


if __name__ == "__main__":
    unittest.main()
