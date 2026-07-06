"""ADR-018 §6.2 — per-page routing decision table."""

from __future__ import annotations

import unittest

from raku_rag.providers.page_routing import (
    PAGE_CLEAN_DIGITAL,
    PAGE_DRAWING,
    PAGE_HANDWRITTEN,
    PAGE_SCANNED,
    PAGE_SEAL,
    PAGE_TABLE_HEAVY,
    PAGE_VERTICAL,
    classify_page_route,
)


class PageRoutingTest(unittest.TestCase):
    def test_clean_digital_default(self) -> None:
        route = classify_page_route({"has_text_layer": True, "is_scanned": False})
        self.assertEqual(route.page_type, PAGE_CLEAN_DIGITAL)
        self.assertEqual(route.primary, "native_text_or_docling")
        self.assertEqual(route.fallback, "ocr_compare")

    def test_scanned_routes_to_ocr(self) -> None:
        self.assertEqual(classify_page_route({"is_scanned": True}).page_type, PAGE_SCANNED)
        self.assertEqual(classify_page_route({"has_text_layer": False}).page_type, PAGE_SCANNED)

    def test_table_heavy(self) -> None:
        route = classify_page_route({"has_text_layer": True, "table_heavy": True})
        self.assertEqual(route.page_type, PAGE_TABLE_HEAVY)
        self.assertEqual(route.primary, "docling_tableformer")

    def test_visual_artefacts_take_precedence(self) -> None:
        # A seal/handwriting/drawing page routes by the artefact even if it also has a text layer.
        self.assertEqual(
            classify_page_route({"has_text_layer": True, "seal_detected": True}).page_type,
            PAGE_SEAL,
        )
        self.assertEqual(
            classify_page_route({"is_scanned": True, "handwriting_detected": True}).page_type,
            PAGE_HANDWRITTEN,
        )
        self.assertEqual(classify_page_route({"drawing_like": True}).page_type, PAGE_DRAWING)

    def test_vertical_japanese(self) -> None:
        route = classify_page_route({"vertical_text_suspected": True})
        self.assertEqual(route.page_type, PAGE_VERTICAL)
        self.assertEqual(route.fallback, "vlm_draft_hitl")

    def test_seal_beats_handwriting_beats_drawing(self) -> None:
        signals = {"seal_detected": True, "handwriting_detected": True, "drawing_like": True}
        self.assertEqual(classify_page_route(signals).page_type, PAGE_SEAL)

    def test_empty_signals_is_clean(self) -> None:
        self.assertEqual(classify_page_route({}).page_type, PAGE_CLEAN_DIGITAL)
        self.assertEqual(classify_page_route(None).page_type, PAGE_CLEAN_DIGITAL)


if __name__ == "__main__":
    unittest.main()
