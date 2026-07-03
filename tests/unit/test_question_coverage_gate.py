"""★G2 — QueryProfile.min_question_coverage no-answer knob (goal.md §1-2).

The check refuses an answer whose USED evidence is not responsive to the QUESTION (post_check
only proves answer⊆evidence). It ships OFF by default: measured coverage does not separate
relevant from irrelevant for short Japanese queries (particles/inflection dilute CJK-bigram
terms), so it is a tenant-tunable opt-in for vocabulary-aligned corpora. These tests pin the
knob's contract AND the documented JP limitation that keeps the default at 0.
"""

from __future__ import annotations

import unittest

from raku_rag.app import MvpSystem
from raku_rag.domain.models import Chunk, QueryProfile, ScopeType, SubjectType
from raku_rag.services.groundedness import GroundednessGate
from tests.helpers import claims


def _chunk(text: str) -> Chunk:
    return Chunk(
        chunk_id="c1",
        tenant_id="t",
        document_id="d1",
        collection_id="col",
        text=text,
        token_count=len(text.split()),
        position=0,
    )


class QuestionCoverageCheckTest(unittest.TestCase):
    def setUp(self) -> None:
        self.gate = GroundednessGate()

    def test_irrelevant_evidence_is_refused_at_threshold(self) -> None:
        # The golden-corpus in-domain gap case: a question about absent content vs an evidence
        # chunk sharing one incidental term ("replacement").
        decision = self.gate.question_coverage_check(
            "What is the standard battery replacement interval for the AGV forklift fleet?",
            [_chunk("The repair history records a sink water leak fixed by packing replacement.")],
            0.34,
        )
        self.assertFalse(decision.passed)
        self.assertIn("coverage", decision.reason)

    def test_responsive_evidence_passes(self) -> None:
        decision = self.gate.question_coverage_check(
            "What does alarm E-142 on press EQ-PRESS-100 indicate?",
            [
                _chunk(
                    "Press machine EQ-PRESS-100 alarm E-142 indicates a temperature sensor "
                    "overheat; reset the controller after the unit has cooled."
                )
            ],
            0.34,
        )
        self.assertTrue(decision.passed)

    def test_zero_threshold_disables_the_check(self) -> None:
        decision = self.gate.question_coverage_check(
            "completely unrelated question about nothing in evidence",
            [_chunk("Press machine alarm reference text.")],
            0.0,
        )
        self.assertTrue(decision.passed)

    def test_documented_jp_limitation_short_followup_scores_below_thresholds(self) -> None:
        # WHY the default is 0.0: a legit short Japanese follow-up against its CORRECT document
        # measures below the irrelevant-English cases, so any global threshold that catches the
        # AGV case would over-refuse this one. Pinned so a future fix must consciously flip it.
        decision = self.gate.question_coverage_check(
            "その圧力の抜き方を教えて",
            [
                _chunk(
                    "蓄圧器の圧力を抜く際は、手動排出弁をゆっくり開いてから配管を開放してください。"
                )
            ],
            0.34,
        )
        self.assertFalse(decision.passed)

    def test_live_answer_path_honors_opt_in_profile(self) -> None:
        # End-to-end: with the knob ON, the grounded-but-irrelevant extraction is refused; the
        # on-topic question still answers. (Default profile keeps the knob OFF — covered by the
        # golden corpus which asserts the in-domain items answer today.)
        system = MvpSystem()
        system.ingest_text(
            tenant_id="t",
            collection_id="col",
            document_id="doc_repair",
            text="The repair history for room U305 records a sink water leak that was fixed "
            "by packing replacement performed by vendor B.",
        )
        system.grant("t", ScopeType.COLLECTION, "col", SubjectType.USER, "alice")
        strict = QueryProfile(min_question_coverage=0.34)
        principal = claims("t", "alice")
        irrelevant = system.answer_service.answer(
            principal,
            "What is the standard battery replacement interval for the AGV forklift fleet?",
            strict,
        )
        self.assertEqual(irrelevant.status, "insufficient_evidence")
        on_topic = system.answer_service.answer(
            principal,
            "How was the sink water leak in room U305 repaired?",
            strict,
        )
        self.assertEqual(on_topic.status, "ok")


if __name__ == "__main__":
    unittest.main()
