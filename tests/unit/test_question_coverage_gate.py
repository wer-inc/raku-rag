"""★G2 — the question-coverage no-answer gates (goal.md §1-2 「"わからない"が言えない」).

Both checks refuse an answer whose USED evidence is not responsive to the QUESTION (post_check
only proves answer⊆evidence). Two generations:

1. `question_coverage_check` (QueryProfile.min_question_coverage, opt-in, default 0=OFF): the
   naive fraction over ALL content terms. Ships OFF because measured coverage does not separate
   relevant from irrelevant for short Japanese queries — particles/inflection dilute the
   CJK-bigram term set (legit 「その圧力の抜き方」 scores 0.17 against its CORRECT doc, below
   irrelevant-English cases at 0.14–0.38). Kept as a tenant-tunable opt-in; its contract and the
   documented JP limitation are pinned below, unchanged.

2. `salient_coverage_check` (QueryProfile.salient_coverage_enabled, default ON): the root-cause
   fix. Coverage is computed over the question's SALIENT terms only — business identifiers
   (query_identifiers) must ALL appear in the evidence (text/document_id/hot metadata fields),
   and >=50% of the salient lexical terms (ASCII content words excluding identifier fragments +
   bigrams within kanji/katakana runs; hiragana runs excluded — that was the dilution) must
   appear in the evidence text. Measured separation (2026-07-03, golden corpus + chatbot/phone/
   U19 follow-up scenarios): must-answer >=0.667, must-refuse <=0.20. This closed the
   goal-gap-audit ★G2 in-domain gap (golden corpus unanswerable_answer_rate 0.2857 -> 0.0,
   risk_weighted_score 0.8621 -> 1.0, over_refusal_rate 0.0 unchanged) and the former baseline
   RATCHET is tightened accordingly (tests/fixtures/eval/golden_baseline.json).
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
        # WHY the naive knob's default is 0.0: a legit short Japanese follow-up against its
        # CORRECT document measures below the irrelevant-English cases, so any global threshold
        # that catches the AGV case would over-refuse this one. Pinned so this knob's semantics
        # never silently change; the SHIPPED fix is salient_coverage_check (which passes this very
        # case — see SalientCoverageCheckTest.test_jp_short_followup_against_correct_doc_passes).
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


class SalientCoverageCheckTest(unittest.TestCase):
    """The root-cause ★G2 gate (default ON): coverage over SALIENT terms only."""

    def setUp(self) -> None:
        self.gate = GroundednessGate()

    def test_in_domain_absent_content_is_refused(self) -> None:
        # The golden-corpus in-domain gap case: one incidental shared term ("replacement") gives
        # salient lexical coverage 1/7 — refused.
        decision = self.gate.salient_coverage_check(
            "What is the standard battery replacement interval for the AGV forklift fleet?",
            [_chunk("The repair history records a sink water leak fixed by packing replacement.")],
        )
        self.assertFalse(decision.passed)
        self.assertIn("coverage", decision.reason)

    def test_identifier_sharing_but_unresponsive_evidence_is_refused(self) -> None:
        # The second in-domain gap case: the evidence names the same equipment (EQ-PRESS-100) but
        # says nothing about torque/bolts. Identifier fragments ("press"/"100") are excluded from
        # the lexical pool, so the shared identifier cannot inflate coverage (1/5 — refused).
        decision = self.gate.salient_coverage_check(
            "What is the recommended torque for the safety cover bolts on press EQ-PRESS-100?",
            [
                _chunk(
                    "Press machine EQ-PRESS-100 alarm E-142 indicates a temperature sensor "
                    "overheat; reset the controller after the unit has cooled."
                )
            ],
        )
        self.assertFalse(decision.passed)

    def test_missing_identifier_is_refused_even_with_high_lexical_coverage(self) -> None:
        # A question about a NONEXISTENT alarm code on real equipment: the generic terms all
        # match, but the named identifier E-999 is absent — refused on the identifier leg.
        decision = self.gate.salient_coverage_check(
            "What does alarm E-999 on press EQ-PRESS-100 indicate?",
            [
                _chunk(
                    "Press machine EQ-PRESS-100 alarm E-142 indicates a temperature sensor "
                    "overheat; reset the controller after the unit has cooled."
                )
            ],
        )
        self.assertFalse(decision.passed)
        self.assertIn("identifier", decision.reason)

    def test_jp_short_followup_against_correct_doc_passes(self) -> None:
        # THE case that kept the naive gate OFF, now separated correctly: the salient term is the
        # kanji run 圧力 (hiragana particles/inflection are excluded), which IS in the correct doc.
        decision = self.gate.salient_coverage_check(
            "その圧力の抜き方を教えて",
            [
                _chunk(
                    "蓄圧器の圧力を抜く際は、手動排出弁をゆっくり開いてから配管を開放してください。"
                )
            ],
        )
        self.assertTrue(decision.passed)

    def test_responsive_english_evidence_passes(self) -> None:
        decision = self.gate.salient_coverage_check(
            "What does alarm E-142 on press EQ-PRESS-100 indicate?",
            [
                _chunk(
                    "Press machine EQ-PRESS-100 alarm E-142 indicates a temperature sensor "
                    "overheat; reset the controller after the unit has cooled."
                )
            ],
        )
        self.assertTrue(decision.passed)

    def test_carried_document_id_is_covered_via_chunk_document_id(self) -> None:
        # A coreference rewrite carries the prior turn's cited DOCUMENT ID into the query; the
        # identifier leg accepts it from chunk.document_id, not just prose.
        chunk = Chunk(
            chunk_id="c1",
            tenant_id="t",
            document_id="routine-inspection-schedule",
            collection_id="col",
            text="Routine inspection of the equipment is performed every 30 days.",
            token_count=10,
            position=0,
        )
        decision = self.gate.salient_coverage_check(
            "How often is routine equipment inspection performed? routine-inspection-schedule",
            [chunk],
        )
        self.assertTrue(decision.passed)

    def test_pii_contact_spans_are_stripped_before_judging(self) -> None:
        # Contact info in the question must never be demanded of the evidence.
        decision = self.gate.salient_coverage_check(
            "maintenance interval for pump P-12? contact alice@example.com or 03-1234-5678",
            [_chunk("The maintenance interval for pump P-12 is ninety days per the manual.")],
        )
        self.assertTrue(decision.passed)

    def test_no_salient_terms_passes(self) -> None:
        # Nothing extractable to judge => never refuse on absent signal.
        decision = self.gate.salient_coverage_check("は?", [_chunk("何らかの文書です。")])
        self.assertTrue(decision.passed)

    def test_live_answer_path_default_on_refuses_absent_content_and_answers_on_topic(self) -> None:
        # End-to-end over MvpSystem with the DEFAULT profile (the knob ships ON): the in-domain
        # absent-content question refuses; the on-topic question still answers.
        system = MvpSystem()
        system.ingest_text(
            tenant_id="t",
            collection_id="col",
            document_id="doc_repair",
            text="The repair history for room U305 records a sink water leak that was fixed "
            "by packing replacement performed by vendor B.",
        )
        system.grant("t", ScopeType.COLLECTION, "col", SubjectType.USER, "alice")
        principal = claims("t", "alice")
        irrelevant = system.answer(
            principal,
            "What is the standard battery replacement interval for the AGV forklift fleet?",
        )
        self.assertEqual(irrelevant.status, "insufficient_evidence")
        on_topic = system.answer(principal, "How was the sink water leak in room U305 repaired?")
        self.assertEqual(on_topic.status, "ok")

    def test_kill_switch_restores_the_old_behavior(self) -> None:
        # salient_coverage_enabled=False replays the pre-fix behavior: the grounded-but-irrelevant
        # extraction answers again (this is exactly the gap the default closes).
        system = MvpSystem()
        system.ingest_text(
            tenant_id="t",
            collection_id="col",
            document_id="doc_repair",
            text="The repair history for room U305 records a sink water leak that was fixed "
            "by packing replacement performed by vendor B.",
        )
        system.grant("t", ScopeType.COLLECTION, "col", SubjectType.USER, "alice")
        off = QueryProfile(salient_coverage_enabled=False)
        answer = system.answer_service.answer(
            claims("t", "alice"),
            "What is the standard battery replacement interval for the AGV forklift fleet?",
            off,
        )
        self.assertEqual(answer.status, "ok")

    def test_intent_query_binds_the_gate_to_what_the_user_asked(self) -> None:
        # A rewrite-enriched query carries a prior-turn doc id the evidence does not contain; with
        # intent_query threaded (the coreference paths do), the gate judges the RAW follow-up and
        # the answer goes through. Without it, the enriched query is judged and refused — the same
        # binding answer_ext.py uses for high-risk classification.
        system = MvpSystem()
        system.ingest_text(
            tenant_id="t",
            collection_id="col",
            document_id="doc_pressure",
            text="蓄圧器の圧力を抜く際は、手動排出弁をゆっくり開いてから配管を開放してください。",
        )
        system.grant("t", ScopeType.COLLECTION, "col", SubjectType.USER, "alice")
        principal = claims("t", "alice")
        enriched = "その圧力の抜き方を教えて carried-prior-turn-doc"
        profile = QueryProfile()
        without_intent = system.answer_service.answer(principal, enriched, profile)
        self.assertEqual(without_intent.status, "insufficient_evidence")
        with_intent = system.answer_service.answer(
            principal, enriched, profile, intent_query="その圧力の抜き方を教えて"
        )
        self.assertEqual(with_intent.status, "ok")


if __name__ == "__main__":
    unittest.main()
