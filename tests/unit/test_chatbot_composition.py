"""L3CompositionAnswerEngine (P4) — offline only, no real network/Bedrock calls anywhere in this
file (mirrors the testing discipline of test_chatbot_envelope.py/test_chatbot_coreference.py).
"""

from __future__ import annotations

import unittest

from raku_rag.chatbot.answer_engine import DialogueContext
from raku_rag.chatbot.composition import (
    L3CompositionAnswerEngine,
    _citation_evidence_chunks,
    verify_composed_answer,
)
from raku_rag.domain.models import IdentityClaims
from raku_rag.services.groundedness import GroundednessGate


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


def _ok_answer(text="根拠に基づく回答です。", document_id="doc_1", citations=None):
    return {
        "status": "ok",
        "text": text,
        "citations": (
            citations
            if citations is not None
            else [
                {
                    "kind": "text",
                    "document_id": document_id,
                    "chunk_id": f"{document_id}:0",
                    "source_id": "src",
                    "version": 1,
                    "retrieval_score": 0.91,
                }
            ]
        ),
        "confidence": 0.88,
        "correlation_id": "trace_rag",
    }


class _RecordingInner:
    """A minimal AnswerEngine-shaped fake that records the query it was called with and returns a
    preconfigured dict (or raises, if configured to)."""

    def __init__(self, response: dict | None = None, raise_error: Exception | None = None) -> None:
        self.calls: list[tuple[str, str | None]] = []
        self._response = response if response is not None else _ok_answer()
        self._raise_error = raise_error

    def answer(self, principal, query, collection_id, context):
        self.calls.append((query, collection_id))
        if self._raise_error is not None:
            raise self._raise_error
        return self._response


class _RaisingGate:
    """A GroundednessGate-shaped fake whose claim_check always raises, to prove
    L3CompositionAnswerEngine fails open rather than crashing the turn."""

    def claim_check(self, answer_text, evidence):
        raise RuntimeError("boom")


class VerifyComposedAnswerTest(unittest.TestCase):
    def setUp(self):
        self.gate = GroundednessGate()
        self.principal = _principal()

    def test_passes_vacuously_when_the_answer_has_no_numeric_or_identifier_claims(self):
        decision = verify_composed_answer(
            self.gate, self.principal, "manuals", "これは通常の状態です。", []
        )
        self.assertTrue(decision.passed)

    def test_passes_when_the_only_claim_is_an_identifier_matching_a_returned_citation(self):
        citations = [{"document_id": "eq-p101", "chunk_id": "eq-p101:0", "source_id": "src"}]
        decision = verify_composed_answer(
            self.gate, self.principal, "manuals", "詳細はeq-p101を参照してください。", citations
        )
        self.assertTrue(decision.passed)

    def test_fails_when_a_claimed_identifier_matches_no_returned_citation(self):
        citations = [{"document_id": "eq-p101", "chunk_id": "eq-p101:0", "source_id": "src"}]
        decision = verify_composed_answer(
            self.gate, self.principal, "manuals", "詳細はeq-p999を参照してください。", citations
        )
        self.assertFalse(decision.passed)

    def test_fails_on_a_numeric_claim_because_citations_carry_no_evidence_text(self):
        # Documents the known, deliberate limitation described in composition.py's module docstring:
        # citations are reference receipts, never evidence text, so a genuinely-grounded numeric claim
        # cannot be independently re-confirmed at this layer -- this is why the engine never lets a
        # failure here override an inner "ok" answer.
        citations = [{"document_id": "eq-p101", "chunk_id": "eq-p101:0", "source_id": "src"}]
        decision = verify_composed_answer(
            self.gate, self.principal, "manuals", "P-101の締付トルクは25N・mです。", citations
        )
        self.assertFalse(decision.passed)

    def test_empty_citations_still_passes_vacuously_for_non_claim_text(self):
        decision = verify_composed_answer(self.gate, self.principal, "manuals", "問題ありません。", [])
        self.assertTrue(decision.passed)


class CitationEvidenceChunksTest(unittest.TestCase):
    def test_builds_evidence_text_from_citation_reference_ids_only(self):
        citations = [
            {"document_id": "eq-p101", "chunk_id": "eq-p101:0", "source_id": "src_a"},
            {"document_id": "eq-p102", "chunk_id": "", "source_id": ""},
        ]
        chunks = _citation_evidence_chunks(_principal(), "manuals", citations)
        self.assertEqual(len(chunks), 1)
        surface = chunks[0].text
        for expected in ("eq-p101", "eq-p101:0", "src_a", "eq-p102"):
            self.assertIn(expected, surface)

    def test_no_citations_yields_empty_evidence_text(self):
        chunks = _citation_evidence_chunks(_principal(), "manuals", [])
        self.assertEqual(chunks[0].text, "")


class L3CompositionAnswerEngineTest(unittest.TestCase):
    def test_query_reaches_inner_byte_identical_regardless_of_thread_state(self):
        # See composition.py's module docstring "Finding": thread-state QUERY enrichment was tried
        # and reverted because it corrupted retrieval/the safety gate's candidate pool. This is the
        # regression pin for that reversal -- a rich previous turn must never change the query string
        # `inner.answer(...)` receives.
        inner = _RecordingInner()
        engine = L3CompositionAnswerEngine(inner)

        engine.answer(_principal(), "そのトルクは？", "manuals", _context())

        self.assertEqual(inner.calls, [("そのトルクは？", "manuals")])

    def test_query_is_unchanged_on_a_first_turn_too(self):
        inner = _RecordingInner()
        engine = L3CompositionAnswerEngine(inner)
        context = _context(
            previous_question=None, previous_answer=None, previous_source_answer_text=None
        )

        engine.answer(_principal(), "P-101の点検手順を教えて", "manuals", context)

        self.assertEqual(inner.calls, [("P-101の点検手順を教えて", "manuals")])

    def test_non_ok_inner_answer_passes_through_unchanged(self):
        inner_response = {
            "status": "insufficient_evidence",
            "text": None,
            "citations": [],
            "confidence": None,
            "correlation_id": "trace_none",
        }
        inner = _RecordingInner(response=inner_response)
        engine = L3CompositionAnswerEngine(inner)

        result = engine.answer(_principal(), "質問", "manuals", _context())

        self.assertEqual(result, inner_response)

    def test_ok_inner_answer_with_empty_text_passes_through_unchanged(self):
        inner_response = _ok_answer(text="")
        inner = _RecordingInner(response=inner_response)
        engine = L3CompositionAnswerEngine(inner)

        result = engine.answer(_principal(), "質問", "manuals", _context())

        self.assertEqual(result, inner_response)

    def test_ok_answer_with_an_unverifiable_numeric_claim_is_still_returned_unchanged(self):
        # The central safety property (see composition.py's module docstring): this engine's OWN
        # (weaker, id-only-evidence) verification failing must NEVER override an inner "ok" answer
        # with something stricter -- it only ever falls back to inner_answer, unchanged, same as when
        # verification passes. Proves the roadmap's "never make things WORSE than the inner answer".
        inner_response = _ok_answer(
            text="P-101の締付トルクは25N・mです。",
            document_id="eq-p101",
        )
        inner = _RecordingInner(response=inner_response)
        engine = L3CompositionAnswerEngine(inner)

        result = engine.answer(_principal(), "そのトルクは？", "manuals", _context())

        self.assertEqual(result, inner_response)
        self.assertEqual(result["text"], "P-101の締付トルクは25N・mです。")
        self.assertEqual(result["status"], "ok")

    def test_ok_answer_that_verifies_cleanly_is_also_returned_unchanged(self):
        inner_response = _ok_answer(text="詳細はeq-p101を参照してください。", document_id="eq-p101")
        inner = _RecordingInner(response=inner_response)
        engine = L3CompositionAnswerEngine(inner)

        result = engine.answer(_principal(), "根拠は？", "manuals", _context())

        self.assertEqual(result, inner_response)

    def test_an_exception_during_verification_does_not_crash_the_turn(self):
        inner_response = _ok_answer(text="P-101の締付トルクは25N・mです。")
        inner = _RecordingInner(response=inner_response)
        engine = L3CompositionAnswerEngine(inner, groundedness_gate=_RaisingGate())

        result = engine.answer(_principal(), "そのトルクは？", "manuals", _context())

        self.assertEqual(result, inner_response)

    def test_an_exception_from_the_inner_engine_itself_propagates_like_every_other_rung(self):
        inner = _RecordingInner(raise_error=RuntimeError("rag backend down"))
        engine = L3CompositionAnswerEngine(inner)

        with self.assertRaises(RuntimeError):
            engine.answer(_principal(), "質問", "manuals", _context())

    def test_default_construction_uses_a_real_groundedness_gate_without_error(self):
        inner = _RecordingInner(response=_ok_answer(text="これは通常の状態です。"))
        engine = L3CompositionAnswerEngine(inner)

        result = engine.answer(_principal(), "状態は？", "manuals", _context())

        self.assertEqual(result["status"], "ok")


if __name__ == "__main__":
    unittest.main()
