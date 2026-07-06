"""ADR-018 §OQ#2 — the quality-gate thresholds are an env-tunable config surface.

These pin that (a) the defaults are the conservative, safety-first values and (b) a deployment / an eval
sweep can retune the gate via RAKU_QT_* without a code change — the mechanism OQ#2 needs to set the real
thresholds once representative documents are measured.
"""

from __future__ import annotations

import os
import unittest
from contextlib import contextmanager

from raku_rag.domain.parsed_document import (
    BLOCK_PARAGRAPH,
    Block,
    ParsedDocument,
    QualityInfo,
    Table,
)
from raku_rag.services.ingestion_quality import (
    EXTRACTION_QUALITY_STATUS_KEY,
    classify_text_extraction_quality,
)
from raku_rag.services.quality_thresholds import (
    DEFAULT_LOW_TABLE_STRUCTURE_CONFIDENCE,
    DEFAULT_MOJIBAKE_HARD_RATIO,
    quality_thresholds,
)
from raku_rag.services.structured_ingestion import classify_parsed_document_quality


@contextmanager
def _env(**values: str):
    saved = {k: os.environ.get(k) for k in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for k, old in saved.items():
            if old is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = old


class QualityThresholdsTest(unittest.TestCase):
    def test_defaults_are_safety_first(self) -> None:
        t = quality_thresholds()
        self.assertEqual(t.mojibake_hard_ratio, DEFAULT_MOJIBAKE_HARD_RATIO)
        self.assertEqual(t.low_table_structure_confidence, DEFAULT_LOW_TABLE_STRUCTURE_CONFIDENCE)

    def test_env_override_reloads_per_call(self) -> None:
        with _env(RAKU_QT_MOJIBAKE_HARD_RATIO="0.5"):
            self.assertEqual(quality_thresholds().mojibake_hard_ratio, 0.5)
        # Back to the default once the env var is gone.
        self.assertEqual(quality_thresholds().mojibake_hard_ratio, DEFAULT_MOJIBAKE_HARD_RATIO)

    def test_garbage_env_falls_back_to_default(self) -> None:
        with _env(RAKU_QT_MOJIBAKE_HARD_RATIO="not-a-number"):
            self.assertEqual(quality_thresholds().mojibake_hard_ratio, DEFAULT_MOJIBAKE_HARD_RATIO)

    def test_mojibake_threshold_tunes_the_text_gate(self) -> None:
        # ~3% replacement chars — quarantined at the default, waved through when the bar is relaxed.
        text = "pump maintenance interval " + "�" * 2
        default = classify_text_extraction_quality(text, raw_size=40)
        self.assertEqual(default[EXTRACTION_QUALITY_STATUS_KEY], "review_required")
        with _env(RAKU_QT_MOJIBAKE_HARD_RATIO="0.9"):
            relaxed = classify_text_extraction_quality(text, raw_size=40)
        self.assertNotEqual(relaxed[EXTRACTION_QUALITY_STATUS_KEY], "review_required")

    def test_table_structure_threshold_tunes_the_document_gate(self) -> None:
        parsed = ParsedDocument(
            blocks=(Block(block_id="b", kind=BLOCK_PARAGRAPH, text="x"),),
            tables=(
                Table(
                    table_id="t",
                    quality=QualityInfo(metrics={"table_structure_confidence": 0.5}),
                ),
            ),
        )
        # 0.5 clears the default 0.40 bar -> accepted.
        self.assertEqual(classify_parsed_document_quality(parsed)[0], "accepted")
        # Raise the bar above 0.5 -> the same table is now quarantined.
        with _env(RAKU_QT_LOW_TABLE_STRUCTURE_CONFIDENCE="0.6"):
            self.assertEqual(classify_parsed_document_quality(parsed)[0], "review_required")


if __name__ == "__main__":
    unittest.main()
