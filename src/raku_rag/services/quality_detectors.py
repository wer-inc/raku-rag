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


VISUAL_ARTIFACT_DETECTORS: dict[str, type] = {"none": NoOpVisualArtifactDetector}


def select_visual_artifact_detector(name: str | None = None) -> VisualArtifactDetector:
    """Pick a detector by name or ``RAKU_VISUAL_ARTIFACT_DETECTOR`` env (default: none)."""

    chosen = (name or os.environ.get(VISUAL_ARTIFACT_DETECTOR_ENV) or "none").strip().lower()
    factory = VISUAL_ARTIFACT_DETECTORS.get(chosen, NoOpVisualArtifactDetector)
    return factory()
