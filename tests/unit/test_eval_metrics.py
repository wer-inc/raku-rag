"""012 (P1-5) — eval quality-depth metrics: deterministic faithfulness term-support.

Pins SC-002: the faithfulness proxy DISCRIMINATES — a fully-supported answer scores 1.0, an answer
asserting terms absent from the evidence scores <1.0, and no overlap (or no text) scores 0.0. This is
the property the old structural ``groundedness`` proxy could not provide.
"""

from __future__ import annotations

import unittest

from raku_rag.eval.runner import _term_support


class TestTermSupportFaithfulness(unittest.TestCase):
    def test_fully_supported_is_one(self) -> None:
        self.assertEqual(
            _term_support(
                "apply lockout tagout",
                "first apply lockout tagout before removing the guard",
            ),
            1.0,
        )

    def test_partially_supported_is_between(self) -> None:
        score = _term_support(
            "apply lockout tagout immediately unsupervised overnight",
            "apply lockout tagout",
        )
        self.assertLess(score, 1.0)
        self.assertGreater(score, 0.0)

    def test_unsupported_is_zero(self) -> None:
        self.assertEqual(
            _term_support("completely unrelated fabricated claim", "apply lockout tagout"), 0.0
        )

    def test_no_answer_text_is_zero(self) -> None:
        self.assertEqual(_term_support(None, "apply lockout tagout"), 0.0)
        self.assertEqual(_term_support("", "apply lockout tagout"), 0.0)


if __name__ == "__main__":
    unittest.main()
