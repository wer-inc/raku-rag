"""ADR-018 §14/§P5 — the golden ingestion-quality gate: false-accept rate must be 0."""

from __future__ import annotations

import unittest

from raku_rag.eval.ingestion_quality_eval import (
    evaluate_ingestion_quality,
    load_golden_ingestion_corpus,
    run_default_golden_eval,
)


class GoldenIngestionEvalTest(unittest.TestCase):
    def test_no_false_accepts_on_golden_corpus(self) -> None:
        report = run_default_golden_eval()
        self.assertGreater(report.gold_blocking_total, 0)
        # §P5 hard gate: nothing that should be quarantined was waved through as retrieval-eligible.
        self.assertEqual(
            report.false_accepts,
            (),
            f"quality gate false-accepted: {report.false_accepts} (predicted={dict(report.predicted)})",
        )
        self.assertEqual(report.false_accept_rate, 0.0)

    def test_classifier_is_not_degenerate(self) -> None:
        # Clean docs must still pass — a classifier that quarantines everything also has 0 false-accepts.
        report = run_default_golden_eval()
        self.assertGreater(report.gold_accepted_total, 0)
        self.assertEqual(report.over_quarantines, ())

    def test_detects_a_weakened_classifier(self) -> None:
        # A degenerate classifier that always says "accepted" must be caught by the false-accept metric.
        _version, cases = load_golden_ingestion_corpus()

        def weak(text, *, raw_size, content_type=None):
            return {"extraction_quality_status": "accepted"}

        report = evaluate_ingestion_quality(cases, classify=weak)
        self.assertGreater(report.false_accept_count, 0)
        self.assertGreater(report.false_accept_rate, 0.0)


if __name__ == "__main__":
    unittest.main()
