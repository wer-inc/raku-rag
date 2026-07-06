"""ADR-018 §6.2 — per-page routing decision.

A single PDF mixes clean body text, tables, scans, drawings, seals and handwriting; §6.2 says to pick a
primary provider (+ fallback) *per page*, not per document. This module is the pure, testable decision
layer: it maps a page's preflight/visual signals onto the §6.2 route table and records the choice so it
lands in the route_trace (§6.3) for review / debug / reprocess / customer explanation.

The DECISION is stdlib-only and always runs; EXECUTION of the exotic routes (cloud DI table OCR, JP
vertical OCR, VLM draft) stays opt-in on the respective providers (§13.1) — this layer just names the
route the page should take.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

# §6.2 page types (the left column of the routing table).
PAGE_CLEAN_DIGITAL = "clean_digital_text"
PAGE_DIGITAL_MOJIBAKE = "digital_mojibake_suspicious"
PAGE_TABLE_HEAVY = "table_heavy"
PAGE_SCANNED = "scanned"
PAGE_VERTICAL = "vertical_japanese"
PAGE_HANDWRITTEN = "handwritten_note"
PAGE_SEAL = "seal_stamp"
PAGE_DRAWING = "drawing_cad"


@dataclass(frozen=True)
class PageRoute:
    """The §6.2 primary route + fallback chosen for one page, plus the page type that selected it."""

    page_type: str
    primary: str
    fallback: str


# page_type -> (primary route, fallback route). Route names are provider-agnostic intents; the concrete
# provider is chosen at execution time (Docling / OCR provider / cloud DI / VLM), all opt-in.
_ROUTES: dict[str, tuple[str, str]] = {
    PAGE_CLEAN_DIGITAL: ("native_text_or_docling", "ocr_compare"),
    PAGE_DIGITAL_MOJIBAKE: ("docling_plus_ocr_compare", "review_required"),
    PAGE_TABLE_HEAVY: ("docling_tableformer", "cloud_di_or_textract_tables"),
    PAGE_SCANNED: ("jp_ocr", "alternate_ocr_or_review"),
    PAGE_VERTICAL: ("jp_ocr_vertical", "vlm_draft_hitl"),
    PAGE_HANDWRITTEN: ("ocr_if_supported", "vlm_draft_hitl"),
    PAGE_SEAL: ("visual_marker_detection", "hitl"),
    PAGE_DRAWING: ("ocr_visible_text_plus_vlm_draft", "hitl"),
}


def _page_type(signals: Mapping[str, object]) -> str:
    s = signals or {}
    # Most-specific visual artefacts first — they dictate the route even on an otherwise digital page.
    if s.get("seal_detected"):
        return PAGE_SEAL
    if s.get("handwriting_detected"):
        return PAGE_HANDWRITTEN
    if s.get("drawing_like"):
        return PAGE_DRAWING
    if s.get("vertical_text_suspected"):
        return PAGE_VERTICAL
    if s.get("table_heavy"):
        return PAGE_TABLE_HEAVY
    if s.get("is_scanned") or s.get("has_text_layer") is False:
        return PAGE_SCANNED
    if s.get("mojibake_suspected"):
        return PAGE_DIGITAL_MOJIBAKE
    return PAGE_CLEAN_DIGITAL


def classify_page_route(signals: Mapping[str, object] | None) -> PageRoute:
    """Map a page's signals onto the §6.2 route table (primary + fallback)."""

    page_type = _page_type(signals or {})
    primary, fallback = _ROUTES[page_type]
    return PageRoute(page_type=page_type, primary=primary, fallback=fallback)
