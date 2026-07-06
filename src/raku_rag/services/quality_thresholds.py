"""ADR-018 §OQ#2 — tunable quality-gate thresholds.

The ADR leaves the exact thresholds (ocr/layout confidence, mojibake ratio, table-structure confidence)
as an Open Question to be set by measuring the Phase-0 Golden Eval Pack. This module makes them a
CONFIG surface (env-overridable, read per call so a deployment or an eval sweep can tune them without a
code change) with the current conservative defaults (false-accept-first, §P5). Values are read at call
time so tests / an eval harness can vary them.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_MOJIBAKE_HARD_RATIO = 0.02
DEFAULT_CONTROL_CHAR_HARD_RATIO = 0.05
DEFAULT_EMPTY_YIELD_MIN_RAW_BYTES = 512
DEFAULT_LOW_OVERALL_CONFIDENCE = 0.35
DEFAULT_LOW_LAYOUT_CONFIDENCE = 0.30
DEFAULT_LOW_TABLE_STRUCTURE_CONFIDENCE = 0.40


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class QualityThresholds:
    mojibake_hard_ratio: float
    control_char_hard_ratio: float
    empty_yield_min_raw_bytes: int
    low_overall_confidence: float
    low_layout_confidence: float
    low_table_structure_confidence: float


def quality_thresholds() -> QualityThresholds:
    """Current quality-gate thresholds, from env (``RAKU_QT_*``) with the safety-first defaults."""

    return QualityThresholds(
        mojibake_hard_ratio=_env_float("RAKU_QT_MOJIBAKE_HARD_RATIO", DEFAULT_MOJIBAKE_HARD_RATIO),
        control_char_hard_ratio=_env_float(
            "RAKU_QT_CONTROL_CHAR_HARD_RATIO", DEFAULT_CONTROL_CHAR_HARD_RATIO
        ),
        empty_yield_min_raw_bytes=int(
            _env_float("RAKU_QT_EMPTY_YIELD_MIN_RAW_BYTES", DEFAULT_EMPTY_YIELD_MIN_RAW_BYTES)
        ),
        low_overall_confidence=_env_float(
            "RAKU_QT_LOW_OVERALL_CONFIDENCE", DEFAULT_LOW_OVERALL_CONFIDENCE
        ),
        low_layout_confidence=_env_float(
            "RAKU_QT_LOW_LAYOUT_CONFIDENCE", DEFAULT_LOW_LAYOUT_CONFIDENCE
        ),
        low_table_structure_confidence=_env_float(
            "RAKU_QT_LOW_TABLE_STRUCTURE_CONFIDENCE", DEFAULT_LOW_TABLE_STRUCTURE_CONFIDENCE
        ),
    )
