"""L2QueryUnderstandingAnswerEngine (P3) — deterministic-only, no LLM/network anywhere.

Mirrors the testing shape of test_chatbot_envelope.py: module-level helper functions get direct unit
tests, then the engine's decision flow (passthrough / reformat-from-citations / rewrite-and-search)
gets tests of its own. The end-to-end "turn 1 names equipment, turn 2 uses a bare pronoun" regression
proof (and the scope-carry adversarial proof) lives in test_chatbot_service.py, alongside the other
ChatbotService-level P0/P1/P2 proofs.
"""

from __future__ import annotations

import unittest

from raku_rag.chatbot.answer_engine import DialogueContext
from raku_rag.chatbot.coreference import (
    L2QueryUnderstandingAnswerEngine,
    answer_from_previous_turn,
    has_own_topic,
    is_referential_followup,
    residual_topic,
    standalone_query,
)
from raku_rag.domain.models import IdentityClaims


def _principal(tenant="tenant_a", user="alice"):
    return IdentityClaims(tenant_id=tenant, user_id=user, roles=())


def _context(**overrides) -> DialogueContext:
    defaults = dict(
        collection_id="manuals",
        previous_question="P-101 の点検手順を教えて",
        previous_answer="結論:\n点検手順は電源停止、外観確認、記録の順です。\n\n根拠:\n- eq-p101",
        previous_source_answer_text="点検手順は電源停止、外観確認、記録の順です。",
        previous_citations=({"document_id": "eq-p101", "chunk_id": "eq-p101:0", "source_id": "src"},),
        previous_document_ids=("eq-p101",),
        source_policy_ids=("pol_collection",),
    )
    defaults.update(overrides)
    return DialogueContext(**defaults)


def _rag_answer(text="根拠に基づく回答です。", document_id="doc_1"):
    return {
        "status": "ok",
        "text": text,
        "citations": [
            {
                "kind": "text",
                "document_id": document_id,
                "chunk_id": f"{document_id}:0",
                "source_id": "src",
                "version": 1,
                "retrieval_score": 0.91,
            }
        ],
        "confidence": 0.88,
        "correlation_id": "trace_rag",
    }


class SpyInnerEngine:
    def __init__(self, response: dict | None = None) -> None:
        self.calls: list[tuple[object, str, object, DialogueContext]] = []
        self._response = response or _rag_answer()

    def answer(self, principal, query, collection_id, context):
        self.calls.append((principal, query, collection_id, context))
        return self._response


class IsReferentialFollowupTest(unittest.TestCase):
    def test_fires_for_adnominal_marker_with_no_identifier_when_previous_question_exists(self):
        self.assertTrue(is_referential_followup("その締付トルクは?", _context()))

    def test_fires_for_pronominal_marker_from_the_shared_query_planner_list(self):
        # "それ" (not "その") comes from query_planner.AMBIGUOUS_REFERENTS itself, proving the
        # shared list is reused rather than duplicated.
        self.assertTrue(is_referential_followup("それの締付トルクは?", _context()))

    def test_fires_for_additional_anaphoric_markers_beyond_the_shared_pronoun_list(self):
        self.assertTrue(is_referential_followup("上記の保持時間は?", _context()))
        self.assertTrue(is_referential_followup("同じ設備の注意点は?", _context()))

    def test_does_not_fire_without_a_previous_question(self):
        self.assertFalse(
            is_referential_followup("その締付トルクは?", _context(previous_question=None))
        )

    def test_does_not_fire_when_message_has_its_own_identifier(self):
        self.assertFalse(is_referential_followup("P-101のその締付トルクは?", _context()))

    def test_does_not_fire_without_any_referential_marker(self):
        self.assertFalse(is_referential_followup("締付トルクは?", _context()))

    def test_does_not_fire_for_a_long_self_contained_narrative_that_happens_to_use_a_marker(self):
        long_narrative = (
            "先ほど点検した際に異音が発生し、それが徐々に大きくなっているのですが原因は何でしょうか"
        )
        self.assertFalse(is_referential_followup(long_narrative, _context()))

    def test_does_not_fire_for_blank_message(self):
        self.assertFalse(is_referential_followup("   ", _context()))


class ResidualTopicTest(unittest.TestCase):
    def test_residual_topic_strips_marker_particle_and_punctuation_leaving_the_topic(self):
        self.assertEqual(residual_topic("その締付トルクは?"), "締付トルク")

    def test_residual_topic_empty_for_pure_elaboration_request(self):
        self.assertEqual(residual_topic("それについてもう少し詳しく教えてください"), "")
        self.assertEqual(residual_topic("それは?"), "")
        self.assertEqual(residual_topic("その件、もう少し詳しく"), "")

    def test_has_own_topic_true_when_a_new_facet_is_named(self):
        self.assertTrue(has_own_topic("その締付トルクは?"))
        self.assertTrue(has_own_topic("上記の耐圧試験の保持時間は?"))

    def test_has_own_topic_false_for_bare_reference_or_pure_elaboration(self):
        self.assertFalse(has_own_topic("それは?"))
        self.assertFalse(has_own_topic("それについてもう少し詳しく教えてください"))
        self.assertFalse(has_own_topic("続けて教えて"))


class StandaloneQueryTest(unittest.TestCase):
    def test_merges_previous_question_identifier_into_the_new_message(self):
        rewritten = standalone_query("その締付トルクは?", _context())

        self.assertIn("その締付トルクは?", rewritten)
        self.assertIn("p-101", rewritten)

    def test_falls_back_to_previous_document_ids_when_question_has_no_identifier(self):
        context = _context(
            previous_question="モータの端子台トルクは?",
            previous_document_ids=("eq-motor-m8-torque",),
        )

        rewritten = standalone_query("その値は?", context)

        self.assertIn("eq-motor-m8-torque", rewritten)

    def test_falls_back_to_lexical_terms_when_neither_identifier_nor_document_id_exists(self):
        context = _context(
            previous_question="モータの端子台トルクは?",
            previous_document_ids=(),
        )

        rewritten = standalone_query("その値は?", context)

        self.assertNotEqual(rewritten, "その値は?")

    def test_does_not_duplicate_an_identifier_already_present_in_either_hyphenated_or_compact_form(
        self,
    ):
        # The query already spells out the identifier, so nothing needs to be (or should be) carried
        # over — this exact input never reaches standalone_query via the real engine (the detector
        # already blocks a message naming its own identifier), but the function must not corrupt an
        # already-self-contained query if called directly.
        rewritten = standalone_query("p-101 のその締付トルクは?", _context())

        self.assertEqual(rewritten, "p-101 のその締付トルクは?")

    def test_returns_message_unchanged_when_previous_question_is_blank(self):
        context = _context(previous_question="", previous_document_ids=())

        self.assertEqual(standalone_query("その値は?", context), "その値は?")


class AnswerFromPreviousTurnTest(unittest.TestCase):
    def test_returns_none_without_previous_citations(self):
        self.assertIsNone(answer_from_previous_turn(_context(previous_citations=())))

    def test_returns_none_without_any_usable_source_text(self):
        context = _context(previous_source_answer_text="", previous_answer="")
        self.assertIsNone(answer_from_previous_turn(context))

    def test_prefers_the_raw_source_answer_text_over_the_formatted_display_answer(self):
        result = answer_from_previous_turn(_context())

        self.assertEqual(result["text"], "点検手順は電源停止、外観確認、記録の順です。")
        self.assertNotIn("結論:", result["text"])

    def test_falls_back_to_the_formatted_answer_when_source_text_is_missing(self):
        context = _context(previous_source_answer_text="", previous_answer="フォーマット済み回答")

        result = answer_from_previous_turn(context)

        self.assertEqual(result["text"], "フォーマット済み回答")

    def test_carries_previous_citations_and_marks_confidence_and_trace_as_unknown(self):
        result = answer_from_previous_turn(_context())

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["citations"], list(_context().previous_citations))
        self.assertIsNone(result["confidence"])
        self.assertIsNone(result["correlation_id"])

    def test_returned_citations_are_copies_not_the_same_dict_objects(self):
        context = _context()
        result = answer_from_previous_turn(context)

        result["citations"][0]["document_id"] = "mutated"

        self.assertEqual(context.previous_citations[0]["document_id"], "eq-p101")


class L2QueryUnderstandingAnswerEngineTest(unittest.TestCase):
    def setUp(self):
        self.principal = _principal()

    def test_self_contained_query_without_a_marker_is_byte_identical_passthrough(self):
        inner = SpyInnerEngine()
        engine = L2QueryUnderstandingAnswerEngine(inner)
        context = _context()

        result = engine.answer(self.principal, "締付トルクの基準は?", "manuals", context)

        self.assertEqual(result, inner._response)
        self.assertEqual(inner.calls, [(self.principal, "締付トルクの基準は?", "manuals", context)])

    def test_query_with_its_own_identifier_is_not_rewritten_even_with_a_marker(self):
        inner = SpyInnerEngine()
        engine = L2QueryUnderstandingAnswerEngine(inner)
        context = _context()

        engine.answer(self.principal, "P-101のその締付トルクは?", "manuals", context)

        self.assertEqual(inner.calls[0][1], "P-101のその締付トルクは?")

    def test_first_turn_with_no_prior_question_is_passthrough(self):
        inner = SpyInnerEngine()
        engine = L2QueryUnderstandingAnswerEngine(inner)
        context = DialogueContext()

        engine.answer(self.principal, "その締付トルクは?", "manuals", context)

        self.assertEqual(inner.calls[0][1], "その締付トルクは?")

    def test_bare_reference_reuses_previous_citations_without_calling_inner(self):
        inner = SpyInnerEngine()
        engine = L2QueryUnderstandingAnswerEngine(inner)
        context = _context()

        result = engine.answer(self.principal, "それについてもう少し詳しく教えてください", "manuals", context)

        self.assertEqual(inner.calls, [])
        self.assertEqual(result["text"], context.previous_source_answer_text)
        self.assertEqual(result["citations"], list(context.previous_citations))

    def test_message_naming_a_new_facet_triggers_rewrite_and_calls_inner_with_merged_query(self):
        inner = SpyInnerEngine()
        engine = L2QueryUnderstandingAnswerEngine(inner)
        context = _context()

        result = engine.answer(self.principal, "その締付トルクは?", "manuals", context)

        self.assertEqual(len(inner.calls), 1)
        called_query = inner.calls[0][1]
        self.assertIn("その締付トルクは?", called_query)
        self.assertIn("p-101", called_query)
        self.assertEqual(result, inner._response)

    def test_falls_through_to_rewrite_when_reformat_has_nothing_to_reuse(self):
        inner = SpyInnerEngine()
        engine = L2QueryUnderstandingAnswerEngine(inner)
        context = _context(previous_citations=())

        engine.answer(self.principal, "それについてもう少し詳しく教えてください", "manuals", context)

        self.assertEqual(len(inner.calls), 1)

    def test_collection_id_and_context_are_forwarded_to_inner_unchanged_on_rewrite(self):
        inner = SpyInnerEngine()
        engine = L2QueryUnderstandingAnswerEngine(inner)
        context = _context()

        engine.answer(self.principal, "その締付トルクは?", "manuals", context)

        self.assertEqual(inner.calls[0][0], self.principal)
        self.assertEqual(inner.calls[0][2], "manuals")
        self.assertEqual(inner.calls[0][3], context)


if __name__ == "__main__":
    unittest.main()
