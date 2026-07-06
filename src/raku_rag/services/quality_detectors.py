"""ADR-018 §8.3/§8.4 quality detectors.

The §8.4 hard-fail table lists conditions that need signals the plain text classifier can't see. This
module provides them in two tiers:

* **stdlib, real** — ``table_structure_confidence`` (table grid integrity) and ``language_consistency``
  (expected-vs-extracted language) are computed deterministically here.
* **pluggable seam** — handwriting / seal / drawing-only detection needs a vision model, so it is an
  opt-in provider (``VisualArtifactDetector``) with a NoOp default. The gate rule that consumes its
  signals is wired regardless, so plugging a real detector immediately enforces the §8.4 condition.

Everything is stdlib-only so the Tier A gate stays fast; the vision detector is lazy/opt-in.
"""

from __future__ import annotations

import importlib.util
import json
import os
from dataclasses import dataclass
from typing import Iterable, Protocol

# --- table structure confidence (§8.3 table_structure_confidence / §8.4 low-structure) ------------

_TABLE_FILL_WEIGHT = (
    0.55  # readable cells dominate: a detected grid whose cells are empty is suspect
)
_TABLE_SHAPE_WEIGHT = 0.25  # a real table has >= 2 rows and >= 2 cols
_TABLE_HEADER_WEIGHT = 0.20


def table_structure_confidence(cells: Iterable) -> float:
    """Heuristic 0..1 confidence that a table's row/column/header/cell structure is intact (§7.6/§8.3).

    Fill (readable cells) dominates, so the "grid detected but cells couldn't be read" case scores low;
    a proper >=2x2 shape and a detected header add confidence. No cells => 0. A misdetected/degenerate
    table scores low, which the §8.4 gate turns into review_required. Exact threshold is eval-driven
    (§OQ#2).
    """

    cells = list(cells)
    if not cells:
        return 0.0
    rows = {getattr(c, "row", 0) for c in cells}
    cols = {getattr(c, "col", 0) for c in cells}
    n_rows, n_cols = len(rows), len(cols)
    declared = n_rows * n_cols
    if declared <= 0:
        return 0.0
    non_empty = sum(1 for c in cells if str(getattr(c, "text", "")).strip())
    fill = min(1.0, non_empty / declared)
    shape = 1.0 if (n_rows >= 2 and n_cols >= 2) else 0.3
    has_header = any(bool(getattr(c, "is_header", False)) for c in cells)
    score = (
        _TABLE_FILL_WEIGHT * fill
        + _TABLE_SHAPE_WEIGHT * shape
        + _TABLE_HEADER_WEIGHT * (1.0 if has_header else 0.5)
    )
    return round(min(1.0, max(0.0, score)), 3)


# --- language consistency (§8.3 language_consistency / §8.4 expected-ja-but-de-japanized) ----------

_JA_MISMATCH_FLOOR = 0.05
_LANG_MIN_CORE_CHARS = 40
_JA_LANG_ALIASES = {"ja", "jp", "jpn", "japanese", "ja-jp", "ja_jp"}


def japanese_char_ratio(text: str) -> float:
    """Fraction of non-space characters that are Hiragana / Katakana / CJK ideographs."""

    core = [ch for ch in (text or "") if not ch.isspace()]
    if not core:
        return 0.0
    ja = 0
    for ch in core:
        o = ord(ch)
        if (
            0x3040 <= o <= 0x30FF  # hiragana + katakana
            or 0x4E00 <= o <= 0x9FFF  # CJK unified ideographs
            or 0x3400 <= o <= 0x4DBF  # CJK ext A
            or 0xFF66 <= o <= 0xFF9D  # half-width katakana
        ):
            ja += 1
    return ja / len(core)


def is_language_mismatch(text: str, expected_language: str | None) -> bool:
    """§8.4 — expected Japanese but the extraction came out abnormally non-Japanese.

    Conservative + opt-in: only fires when a source declares ``expected_language`` Japanese AND the
    text is long enough to judge AND the Japanese ratio is near-zero (an extraction/encoding failure,
    not a legitimately English document choice — those tenants simply don't set expected_language=ja).
    """

    if not expected_language or expected_language.strip().lower() not in _JA_LANG_ALIASES:
        return False
    core = [ch for ch in (text or "") if not ch.isspace()]
    if len(core) < _LANG_MIN_CORE_CHARS:
        return False
    return japanese_char_ratio(text) < _JA_MISMATCH_FLOOR


# --- drawing-like page heuristic (§8.3 drawing_like) ----------------------------------------------

_DRAWING_MAX_TEXT_CHARS = 24


def is_drawing_like(*, has_figures: bool, text_char_count: int) -> bool:
    """A page dominated by figures with almost no extracted text reads as a drawing/CAD page (§8.3).

    Stdlib heuristic (no vision): figures present + near-zero text. The §8.4 "drawing page yields only
    OCR fragments" condition combines this with the OCR route.
    """

    return bool(has_figures) and text_char_count <= _DRAWING_MAX_TEXT_CHARS


# --- §8.3 derived quality dimension vector --------------------------------------------------------


def _page_signal(pages, key: str) -> float:
    return 1.0 if any(dict(getattr(p, "signals", {}) or {}).get(key) for p in pages) else 0.0


def document_quality_dimensions(parsed, *, expected_language: str = "") -> dict[str, float]:
    """Compute the deterministic subset of the §8.3 dimension vector from a ParsedDocument.

    Complements the provider-confidence dims (layout/ocr from Docling) with signals derivable from the
    normalized document: text_yield, empty_page_risk, mojibake_risk, reading_order_risk,
    cell_anchor_coverage, visual_coverage, provider_error, and the 0/1 detector dims
    (drawing_like / handwriting_detected / seal_detected). Values are heuristic; thresholds are
    eval-driven (§OQ#2).
    """

    blocks = list(getattr(parsed, "blocks", ()) or ())
    pages = list(getattr(parsed, "pages", ()) or ())
    figures = list(getattr(parsed, "figures", ()) or ())
    tables = list(getattr(parsed, "tables", ()) or ())
    dims: dict[str, float] = {}

    doc_text = parsed.text_for_embedding() if hasattr(parsed, "text_for_embedding") else ""
    if doc_text:
        replacement = doc_text.count("�")
        control = sum(1 for ch in doc_text if ord(ch) < 32 and ch not in "\t\n\r")
        dims["mojibake_risk"] = round((replacement + control) / len(doc_text), 4)
    if expected_language:
        dims["language_consistency"] = (
            round(japanese_char_ratio(doc_text), 4)
            if expected_language.strip().lower() in _JA_LANG_ALIASES
            else 1.0
        )

    orders = [b.reading_order for b in blocks if getattr(b, "reading_order", None) is not None]
    if len(orders) >= 2:
        inversions = sum(1 for a, b in zip(orders, orders[1:]) if b < a)
        dims["reading_order_risk"] = round(inversions / (len(orders) - 1), 4)

    if pages:
        text_pages = {
            b.page_no for b in blocks if b.page_no and str(getattr(b, "text", "") or "").strip()
        }
        dims["text_yield"] = round(len(text_pages) / len(pages), 4)
        dims["empty_page_risk"] = round(
            sum(1 for p in pages if p.page_no not in text_pages) / len(pages), 4
        )
        dims["drawing_like"] = _page_signal(pages, "drawing_like")
        dims["handwriting_detected"] = _page_signal(pages, "handwriting_detected")
        dims["seal_detected"] = _page_signal(pages, "seal_detected")

    if figures:
        captioned = sum(1 for f in figures if str(getattr(f, "caption", "") or "").strip())
        dims["visual_coverage"] = round(captioned / len(figures), 4)

    if tables:
        dims["cell_anchor_coverage"] = round(
            sum(1 for t in tables if getattr(t, "cells", ())) / len(tables), 4
        )
        tscs = [
            dict(getattr(t, "quality", None).metrics or {}).get("table_structure_confidence")
            for t in tables
            if getattr(t, "quality", None) is not None
        ]
        tscs = [x for x in tscs if x is not None]
        if tscs:
            dims["table_structure_confidence"] = min(tscs)

    error_results = {"unavailable", "review_required", "rejected"}
    dims["provider_error"] = (
        1.0
        if any(
            getattr(s, "result", "") in error_results for s in getattr(parsed, "route_trace", ())
        )
        else 0.0
    )
    return dims


# --- visual artifact detector seam (§8.4 handwriting / seal — needs vision, opt-in) ----------------

VISUAL_ARTIFACT_DETECTOR_ENV = "RAKU_VISUAL_ARTIFACT_DETECTOR"


@dataclass(frozen=True)
class VisualArtifactSignals:
    handwriting_detected: bool = False
    seal_detected: bool = False
    drawing_like: bool = False

    def any(self) -> bool:
        return self.handwriting_detected or self.seal_detected or self.drawing_like


class VisualArtifactDetector(Protocol):
    name: str

    def available(self) -> bool: ...

    def detect(self, image_png: bytes, *, page_no: int) -> VisualArtifactSignals: ...


class NoOpVisualArtifactDetector:
    """Default: no vision detector. Handwriting/seal are not guessed — they simply aren't flagged."""

    name = "none"

    def available(self) -> bool:
        return False

    def detect(self, image_png: bytes, *, page_no: int) -> VisualArtifactSignals:
        return VisualArtifactSignals()


class CallableVisualArtifactDetector:
    """Adapter around ``callable(image_png, page_no) -> VisualArtifactSignals`` (injection / tests)."""

    name = "callable"

    def __init__(self, fn, *, available: bool = True) -> None:
        self._fn = fn
        self._available = available

    def available(self) -> bool:
        return self._available

    def detect(self, image_png: bytes, *, page_no: int) -> VisualArtifactSignals:
        return self._fn(image_png, page_no) or VisualArtifactSignals()


BEDROCK_VISION_MODEL_ENV = "RAKU_BEDROCK_VISION_MODEL_ID"
_DEFAULT_BEDROCK_VISION_MODEL_ID = "jp.anthropic.claude-sonnet-4-5-20250929-v1:0"
_ARTIFACT_PROMPT = (
    "Classify this document page image for extraction-quality triage. Respond with ONLY a compact JSON "
    'object with three boolean fields: {"handwriting": <bool>, "seal": <bool>, "drawing": <bool>}. '
    "handwriting = handwritten text or annotations are present; seal = a stamp / hanko / inkan seal is "
    "present; drawing = the page is primarily a technical drawing, diagram, or schematic with little "
    "body text. Output only the JSON object, no prose."
)


def _parse_artifact_signals(raw: str) -> VisualArtifactSignals:
    """Parse the VLM's JSON reply into signals. Any parse failure yields no flags (safe additive default)."""

    text = raw or ""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return VisualArtifactSignals()
    try:
        obj = json.loads(text[start : end + 1])
    except (ValueError, TypeError):
        return VisualArtifactSignals()
    if not isinstance(obj, dict):
        return VisualArtifactSignals()
    return VisualArtifactSignals(
        handwriting_detected=bool(obj.get("handwriting")),
        seal_detected=bool(obj.get("seal")),
        drawing_like=bool(obj.get("drawing")),
    )


class BedrockVisualArtifactDetector:
    """Real handwriting/seal/drawing detector via Amazon Bedrock (Claude vision). Opt-in, §19 gated.

    A positive signal routes the page to ``review_required`` (§8.4), so this only ever *adds* review
    items — it never waves anything through. Stays unavailable unless boto3 is present and
    ``RAKU_ALLOW_CLOUD_EGRESS`` is set. Tests inject ``invoker`` to validate parsing offline.
    """

    name = "bedrock"

    def __init__(
        self, *, invoker=None, model_id: str | None = None, region: str | None = None
    ) -> None:
        self._invoker = invoker
        self._model_id = (
            model_id or os.environ.get(BEDROCK_VISION_MODEL_ENV) or _DEFAULT_BEDROCK_VISION_MODEL_ID
        )
        self._region = region

    def available(self) -> bool:
        if self._invoker is not None:
            return True
        from raku_rag.providers.ocr.pluggable import cloud_egress_allowed

        return cloud_egress_allowed() and importlib.util.find_spec("boto3") is not None

    def _resolve_invoker(self):
        if self._invoker is None:
            from raku_rag.providers.aws_visual import build_bedrock_vision_invoker

            self._invoker = (
                build_bedrock_vision_invoker(region_name=self._region)
                if self._region
                else build_bedrock_vision_invoker()
            )
        return self._invoker

    def detect(self, image_png: bytes, *, page_no: int) -> VisualArtifactSignals:
        if not self.available():
            return VisualArtifactSignals()
        raw = self._resolve_invoker()(
            model_id=self._model_id, prompt=_ARTIFACT_PROMPT, image=image_png, max_tokens=200
        )
        return _parse_artifact_signals(raw)


VISUAL_ARTIFACT_DETECTORS: dict[str, type] = {
    "none": NoOpVisualArtifactDetector,
    "bedrock": BedrockVisualArtifactDetector,
}


def select_visual_artifact_detector(name: str | None = None) -> VisualArtifactDetector:
    """Pick a detector by name or ``RAKU_VISUAL_ARTIFACT_DETECTOR`` env (default: none)."""

    chosen = (name or os.environ.get(VISUAL_ARTIFACT_DETECTOR_ENV) or "none").strip().lower()
    factory = VISUAL_ARTIFACT_DETECTORS.get(chosen, NoOpVisualArtifactDetector)
    return factory()
