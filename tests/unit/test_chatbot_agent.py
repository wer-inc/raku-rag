"""L4AgenticAnswerEngine (P5) — offline only, no real network/Bedrock calls anywhere in this file
(mirrors the testing discipline of test_chatbot_composition.py/test_chatbot_coreference.py). All
decision-makers here are hand-written fakes/mocks, exactly like `tests/unit/test_bedrock_claude_llm.py`
mocks an LLM invoker. End-to-end safety tests against a REAL `ManufacturingSystem` (the central
adversarial test, ACL-reassertion, and the hop cap) live in `tests/unit/test_chatbot_service.py`
alongside every other rung's own high-risk tests; this file pins the engine's OWN decision logic in
isolation, independent of any manufacturing-specific classifier.
"""

from __future__ import annotations

import dataclasses
import unittest

from raku_rag.chatbot.agent import (
    DEFAULT_MAX_HOPS,
    AgentObservation,
    FinishAction,
    L4AgenticAnswerEngine,
    RetrieveAction,
    _observation_from,
)
from raku_rag.chatbot.answer_engine import DialogueContext
from raku_rag.domain.models import IdentityClaims


def _principal(tenant="tenant_a", user="alice"):
    return IdentityClaims(tenant_id=tenant, user_id=user, roles=())


def _context(**overrides) -> DialogueContext:
    defaults = dict(collection_id="manuals")
    defaults.update(overrides)
    return DialogueContext(**defaults)


def _ok_answer(text="根拠に基づく回答です。", document_id="doc_1"):
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


def _insufficient_answer():
    return {
        "status": "insufficient_evidence",
        "text": None,
        "citations": [],
        "confidence": None,
        "correlation_id": "trace_none",
    }


class _QueryRoutedInner:
    """AnswerEngine-shaped fake returning a per-query preconfigured response (or a default),
    recording every query it was actually called with, in order."""

    def __init__(self, responses: dict[str, dict], default: dict | None = None):
        self._responses = responses
        self._default = default if default is not None else _insufficient_answer()
        self.calls: list[str] = []

    def answer(self, principal, query, collection_id, context):
        self.calls.append(query)
        return self._responses.get(query, self._default)


class _RecordingInner:
    """A minimal AnswerEngine-shaped fake that always returns the same preconfigured response and
    records every call's full argument tuple."""

    def __init__(self, response: dict | None = None) -> None:
        self.calls: list[tuple] = []
        self._response = response if response is not None else _ok_answer()

    def answer(self, principal, query, collection_id, context):
        self.calls.append((principal, query, collection_id, context))
        return self._response


class _ScriptedDecisionMaker:
    """Returns one action per call from a fixed script, then `FinishAction()` forever after the
    script is exhausted. Also records every call's arguments for inspection."""

    def __init__(self, actions):
        self._actions = list(actions)
        self.calls: list[tuple] = []

    def decide(self, query, context, observations):
        self.calls.append((query, context, observations))
        index = len(self.calls) - 1
        if index < len(self._actions):
            return self._actions[index]
        return FinishAction()


class _AlwaysRetrieveDecisionMaker:
    """Adversarial: never finishes, always proposes one more hop -- used to prove the hop cap."""

    def __init__(self, query_prefix: str = "probe"):
        self._query_prefix = query_prefix
        self.calls = 0

    def decide(self, query, context, observations):
        self.calls += 1
        return RetrieveAction(f"{self._query_prefix}-{self.calls}")


class _RaisingDecisionMaker:
    def __init__(self, fail_on_call: int):
        self._fail_on_call = fail_on_call
        self.calls = 0

    def decide(self, query, context, observations):
        self.calls += 1
        if self.calls == self._fail_on_call:
            raise RuntimeError("decision-maker exploded")
        return RetrieveAction(f"query-{self.calls}")


class _MalformedDecisionMaker:
    """Returns something that is not a recognized AgentAction at all -- the "output guard" case."""

    def __init__(self, malformed_on_call: int = 1):
        self._malformed_on_call = malformed_on_call
        self.calls = 0

    def decide(self, query, context, observations):
        self.calls += 1
        if self.calls == self._malformed_on_call:
            return "not-an-action"
        return RetrieveAction(f"query-{self.calls}")


class AgentObservationFromTest(unittest.TestCase):
    def test_builds_a_reference_only_observation_from_an_ok_answer(self):
        observation = _observation_from("q1", _ok_answer(document_id="eq-p101"))

        self.assertEqual(observation.query, "q1")
        self.assertEqual(observation.status, "ok")
        self.assertTrue(observation.answerable)
        self.assertEqual(observation.citation_ids, ("eq-p101", "eq-p101:0", "src"))

    def test_builds_an_unanswerable_observation_from_an_insufficient_answer(self):
        observation = _observation_from("q1", _insufficient_answer())

        self.assertEqual(observation.status, "insufficient_evidence")
        self.assertFalse(observation.answerable)
        self.assertEqual(observation.citation_ids, ())

    def test_ok_status_with_no_citations_is_not_treated_as_answerable(self):
        observation = _observation_from("q1", {"status": "ok", "text": "x", "citations": []})

        self.assertFalse(observation.answerable)

    def test_agent_observation_never_carries_a_free_text_field_beyond_the_query_it_produced(self):
        # Structural pin for the module docstring's injection-hardening property: an observation can
        # only ever surface `query` (the decision-maker's OWN prior proposal, echoed back -- not new
        # untrusted content), `status`, `answerable`, and `citation_ids` (reference IDs only). No
        # evidence/answer TEXT field exists for a future real decision-maker to misinterpret as an
        # instruction, because retrieved content never reaches this loop as text in the first place.
        fields = {f.name for f in dataclasses.fields(AgentObservation)}
        self.assertEqual(fields, {"query", "status", "answerable", "citation_ids"})


class L4AgenticAnswerEngineConstructionTest(unittest.TestCase):
    def test_default_construction_uses_the_default_max_hops_without_error(self):
        engine = L4AgenticAnswerEngine(_RecordingInner())
        self.assertEqual(engine._max_hops, DEFAULT_MAX_HOPS)

    def test_rejects_a_non_positive_max_hops(self):
        with self.assertRaises(ValueError):
            L4AgenticAnswerEngine(_RecordingInner(), max_hops=0)


class L4AgenticAnswerEngineNoDecisionMakerTest(unittest.TestCase):
    """Mirrors L1EnvelopeAnswerEngine's/L3CompositionAnswerEngine's own "no provider configured"
    no-op stance: `decision_maker=None` (the default -- no real one exists yet) must be a
    byte-identical, zero-extra-call passthrough to `inner.answer(query, ...)` with the ORIGINAL turn
    query, unchanged."""

    def test_passes_through_to_inner_with_the_original_query_unchanged(self):
        inner = _RecordingInner()
        engine = L4AgenticAnswerEngine(inner)
        principal = _principal()
        context = _context()

        result = engine.answer(principal, "original question", "manuals", context)

        self.assertEqual(inner.calls, [(principal, "original question", "manuals", context)])
        self.assertEqual(result, inner._response)

    def test_is_the_default_when_no_decision_maker_keyword_is_given(self):
        inner = _RecordingInner()
        engine = L4AgenticAnswerEngine(inner, high_risk_query_signal=lambda q: True)

        # Even a signal that would ALWAYS trip has no effect at all when there is no decision-maker
        # to propose a hop in the first place -- the check only ever runs on a PROPOSED hop query.
        engine.answer(_principal(), "original question", "manuals", _context())

        self.assertEqual(inner.calls[0][1], "original question")


class L4AgenticAnswerEngineSingleHopTest(unittest.TestCase):
    def test_one_retrieve_then_finish_calls_inner_exactly_once_with_the_hop_query(self):
        inner = _QueryRoutedInner({"hop-query": _ok_answer(document_id="doc_hop")})
        decision_maker = _ScriptedDecisionMaker([RetrieveAction("hop-query")])
        engine = L4AgenticAnswerEngine(inner, decision_maker=decision_maker)

        result = engine.answer(_principal(), "original question", "manuals", _context())

        self.assertEqual(inner.calls, ["hop-query"])
        self.assertEqual(result["citations"][0]["document_id"], "doc_hop")

    def test_finish_as_the_very_first_decision_never_calls_inner_and_falls_back_to_the_floor(self):
        inner = _QueryRoutedInner(
            {"original question": _ok_answer(document_id="doc_floor")},
        )
        decision_maker = _ScriptedDecisionMaker([FinishAction()])
        engine = L4AgenticAnswerEngine(inner, decision_maker=decision_maker)

        result = engine.answer(_principal(), "original question", "manuals", _context())

        self.assertEqual(inner.calls, ["original question"])
        self.assertEqual(result["citations"][0]["document_id"], "doc_floor")

    def test_decide_receives_the_original_query_context_and_empty_observations_on_the_first_call(self):
        inner = _RecordingInner()
        decision_maker = _ScriptedDecisionMaker([FinishAction()])
        engine = L4AgenticAnswerEngine(inner, decision_maker=decision_maker)
        context = _context(previous_question="prior?")

        engine.answer(_principal(), "original question", "manuals", context)

        called_query, called_context, called_observations = decision_maker.calls[0]
        self.assertEqual(called_query, "original question")
        self.assertIs(called_context, context)
        self.assertEqual(called_observations, ())


class L4AgenticAnswerEngineMultiHopTest(unittest.TestCase):
    def test_hops_run_in_order_with_the_decision_makers_own_chosen_query_text(self):
        inner = _QueryRoutedInner(
            {
                "hop-1": _insufficient_answer(),
                "hop-2": _ok_answer(document_id="doc_2"),
            }
        )
        decision_maker = _ScriptedDecisionMaker([RetrieveAction("hop-1"), RetrieveAction("hop-2")])
        engine = L4AgenticAnswerEngine(inner, decision_maker=decision_maker)

        result = engine.answer(_principal(), "original question", "manuals", _context())

        self.assertEqual(inner.calls, ["hop-1", "hop-2"])
        self.assertEqual(result["citations"][0]["document_id"], "doc_2")

    def test_later_decide_calls_receive_prior_hops_as_reference_only_observations(self):
        inner = _QueryRoutedInner({"hop-1": _ok_answer(document_id="doc_1")})
        decision_maker = _ScriptedDecisionMaker([RetrieveAction("hop-1"), RetrieveAction("hop-2")])
        engine = L4AgenticAnswerEngine(inner, decision_maker=decision_maker)

        engine.answer(_principal(), "original question", "manuals", _context())

        _, _, observations_on_second_call = decision_maker.calls[1]
        self.assertEqual(len(observations_on_second_call), 1)
        observation = observations_on_second_call[0]
        self.assertEqual(observation.query, "hop-1")
        self.assertEqual(observation.status, "ok")
        self.assertTrue(observation.answerable)
        self.assertEqual(observation.citation_ids, ("doc_1", "doc_1:0", "src"))

    def test_last_hop_wins_a_later_failure_does_not_discard_an_earlier_success(self):
        # "Last hop wins" (module docstring): if the decision-maker, having already found a good
        # answer, asks for ANOTHER hop that comes back empty, the LATER (empty) result is what the
        # turn surfaces -- never a merge, and never silently reverting to the earlier one either. See
        # the reverse case below for why "last hop wins" specifically (not "first/best ok hop wins").
        inner = _QueryRoutedInner(
            {
                "hop-1-good": _ok_answer(document_id="doc_good"),
                "hop-2-empty": _insufficient_answer(),
            }
        )
        decision_maker = _ScriptedDecisionMaker(
            [RetrieveAction("hop-1-good"), RetrieveAction("hop-2-empty")]
        )
        engine = L4AgenticAnswerEngine(inner, decision_maker=decision_maker)

        result = engine.answer(_principal(), "original question", "manuals", _context())

        self.assertEqual(result["status"], "insufficient_evidence")
        self.assertEqual(result["citations"], [])

    def test_last_hop_wins_a_later_success_is_surfaced_over_an_earlier_failure(self):
        inner = _QueryRoutedInner(
            {
                "hop-1-empty": _insufficient_answer(),
                "hop-2-good": _ok_answer(document_id="doc_good"),
            }
        )
        decision_maker = _ScriptedDecisionMaker(
            [RetrieveAction("hop-1-empty"), RetrieveAction("hop-2-good")]
        )
        engine = L4AgenticAnswerEngine(inner, decision_maker=decision_maker)

        result = engine.answer(_principal(), "original question", "manuals", _context())

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["citations"][0]["document_id"], "doc_good")

    def test_final_answer_is_never_a_merge_of_two_hops_citations(self):
        inner = _QueryRoutedInner(
            {
                "hop-1": _ok_answer(document_id="doc_1"),
                "hop-2": _ok_answer(document_id="doc_2"),
            }
        )
        decision_maker = _ScriptedDecisionMaker([RetrieveAction("hop-1"), RetrieveAction("hop-2")])
        engine = L4AgenticAnswerEngine(inner, decision_maker=decision_maker)

        result = engine.answer(_principal(), "original question", "manuals", _context())

        document_ids = [c["document_id"] for c in result["citations"]]
        self.assertEqual(document_ids, ["doc_2"], "must be exactly ONE hop's own citations, never both")

    def test_every_hop_reuses_the_same_fixed_principal_and_collection_id(self):
        # Module docstring point 4: the loop's only freedom is query text -- it never constructs its
        # own principal/collection_id, so scope cannot vary hop-to-hop by construction.
        inner = _RecordingInner()
        decision_maker = _ScriptedDecisionMaker([RetrieveAction("hop-1"), RetrieveAction("hop-2")])
        engine = L4AgenticAnswerEngine(inner, decision_maker=decision_maker)
        principal = _principal()
        context = _context()

        engine.answer(principal, "original question", "manuals", context)

        self.assertEqual(len(inner.calls), 2)
        for call_principal, _query, call_collection_id, call_context in inner.calls:
            self.assertIs(call_principal, principal)
            self.assertEqual(call_collection_id, "manuals")
            self.assertIs(call_context, context)


class L4AgenticAnswerEngineHopCapTest(unittest.TestCase):
    def test_infinite_retry_decision_maker_is_stopped_at_the_default_cap(self):
        inner = _RecordingInner()
        decision_maker = _AlwaysRetrieveDecisionMaker()
        engine = L4AgenticAnswerEngine(inner, decision_maker=decision_maker)

        engine.answer(_principal(), "original question", "manuals", _context())

        self.assertEqual(decision_maker.calls, DEFAULT_MAX_HOPS)
        self.assertEqual(len(inner.calls), DEFAULT_MAX_HOPS)

    def test_infinite_retry_decision_maker_is_stopped_at_a_custom_lower_cap(self):
        inner = _RecordingInner()
        decision_maker = _AlwaysRetrieveDecisionMaker()
        engine = L4AgenticAnswerEngine(inner, decision_maker=decision_maker, max_hops=1)

        result = engine.answer(_principal(), "original question", "manuals", _context())

        self.assertEqual(decision_maker.calls, 1)
        self.assertEqual(len(inner.calls), 1)
        self.assertEqual(result, inner._response)

    def test_hop_cap_exceeded_returns_the_last_hops_own_result_not_an_extra_floor_call(self):
        # "Last hop wins" (module docstring) applies uniformly to every loop-terminating condition,
        # including running out of hops: once ANY hop has actually run, its own (possibly
        # non-"ok") result is authoritative -- there is no additional, implicit floor call tacked on
        # using yet a THIRD query (the original text) after the cap is hit. Only a decision-maker
        # that never gets a single hop to run at all (see the no-decision-maker/Finish-first tests
        # above) falls back to the floor.
        inner = _QueryRoutedInner({}, default=_insufficient_answer())
        decision_maker = _AlwaysRetrieveDecisionMaker()
        engine = L4AgenticAnswerEngine(inner, decision_maker=decision_maker, max_hops=2)

        result = engine.answer(_principal(), "original question", "manuals", _context())

        self.assertEqual(inner.calls, ["probe-1", "probe-2"])
        self.assertEqual(result["status"], "insufficient_evidence")


class L4AgenticAnswerEngineHighRiskSignalTest(unittest.TestCase):
    """`high_risk_query_signal` (see module docstring): gates EVERY hop's proposed query, not just
    the first, and a trip aborts the whole turn -- discarding any earlier hop's result -- rather than
    just skipping the offending hop. Uses a fake callback here (the real one, in production, is
    `ManufacturingSystem.is_high_risk_query_signal` -- proven end-to-end against a real
    `ManufacturingSystem` in `tests/unit/test_chatbot_service.py`'s
    `ChatbotL4AgenticHighRiskSafetyTest`)."""

    def _spy_signal(self, hazardous_queries: set[str]):
        calls: list[str] = []

        def signal(query: str) -> bool:
            calls.append(query)
            return query in hazardous_queries

        return signal, calls

    def test_a_hazardous_first_hop_never_reaches_inner_and_falls_back_to_the_original_query(self):
        inner = _QueryRoutedInner({"original question": _ok_answer(document_id="doc_floor")})
        signal, calls = self._spy_signal({"hazardous-hop"})
        decision_maker = _ScriptedDecisionMaker([RetrieveAction("hazardous-hop")])
        engine = L4AgenticAnswerEngine(
            inner, decision_maker=decision_maker, high_risk_query_signal=signal
        )

        result = engine.answer(_principal(), "original question", "manuals", _context())

        self.assertEqual(calls, ["hazardous-hop"])
        self.assertNotIn("hazardous-hop", inner.calls)
        self.assertEqual(inner.calls, ["original question"])
        self.assertEqual(result["citations"][0]["document_id"], "doc_floor")

    def test_a_hazardous_later_hop_discards_an_earlier_good_hop_and_falls_back(self):
        inner = _QueryRoutedInner(
            {
                "benign-hop": _ok_answer(document_id="doc_benign"),
                "original question": _ok_answer(document_id="doc_floor"),
            }
        )
        signal, calls = self._spy_signal({"hazardous-hop"})
        decision_maker = _ScriptedDecisionMaker(
            [RetrieveAction("benign-hop"), RetrieveAction("hazardous-hop")]
        )
        engine = L4AgenticAnswerEngine(
            inner, decision_maker=decision_maker, high_risk_query_signal=signal
        )

        result = engine.answer(_principal(), "original question", "manuals", _context())

        self.assertEqual(calls, ["benign-hop", "hazardous-hop"], "checked on EVERY hop, not just the first")
        self.assertNotIn("hazardous-hop", inner.calls)
        self.assertEqual(
            result["citations"][0]["document_id"],
            "doc_floor",
            "the earlier benign hop's good answer must be discarded, not silently reused",
        )

    def test_signal_returning_false_for_every_hop_leaves_normal_multi_hop_unaffected(self):
        inner = _QueryRoutedInner({"hop-1": _ok_answer(document_id="doc_1")})
        signal, calls = self._spy_signal(set())
        decision_maker = _ScriptedDecisionMaker([RetrieveAction("hop-1")])
        engine = L4AgenticAnswerEngine(
            inner, decision_maker=decision_maker, high_risk_query_signal=signal
        )

        result = engine.answer(_principal(), "original question", "manuals", _context())

        self.assertEqual(calls, ["hop-1"])
        self.assertEqual(result["citations"][0]["document_id"], "doc_1")

    def test_default_with_no_signal_wired_never_blocks_any_hop(self):
        inner = _QueryRoutedInner({"any-hop-text": _ok_answer(document_id="doc_1")})
        decision_maker = _ScriptedDecisionMaker([RetrieveAction("any-hop-text")])
        engine = L4AgenticAnswerEngine(inner, decision_maker=decision_maker)  # no signal at all

        result = engine.answer(_principal(), "original question", "manuals", _context())

        self.assertEqual(inner.calls, ["any-hop-text"])
        self.assertEqual(result["citations"][0]["document_id"], "doc_1")


class L4AgenticAnswerEngineDecisionMakerOutputGuardTest(unittest.TestCase):
    """The controller's own output is untrusted, not obeyed blindly -- the new failure surface this
    rung introduces (module docstring point 6). An exception or an unrecognized returned value both
    stop the loop safely rather than propagate/crash or guess at intent."""

    def test_an_exception_on_the_first_decide_call_falls_back_to_the_floor(self):
        inner = _QueryRoutedInner({"original question": _ok_answer(document_id="doc_floor")})
        decision_maker = _RaisingDecisionMaker(fail_on_call=1)
        engine = L4AgenticAnswerEngine(inner, decision_maker=decision_maker)

        result = engine.answer(_principal(), "original question", "manuals", _context())

        self.assertEqual(inner.calls, ["original question"])
        self.assertEqual(result["citations"][0]["document_id"], "doc_floor")

    def test_an_exception_on_a_later_decide_call_preserves_an_earlier_good_hop(self):
        # Unlike a high-risk-signal trip, a malformed/crashing LATER decision is not itself evidence
        # that an earlier, already-fully-gated hop's answer is untrustworthy -- so it is preserved,
        # not discarded (module docstring point 6 vs. point 2 -- these are deliberately different).
        inner = _QueryRoutedInner({"query-1": _ok_answer(document_id="doc_1")})
        decision_maker = _RaisingDecisionMaker(fail_on_call=2)
        engine = L4AgenticAnswerEngine(inner, decision_maker=decision_maker)

        result = engine.answer(_principal(), "original question", "manuals", _context())

        self.assertEqual(inner.calls, ["query-1"])
        self.assertEqual(result["citations"][0]["document_id"], "doc_1")

    def test_an_unrecognized_returned_value_on_the_first_call_falls_back_to_the_floor(self):
        inner = _QueryRoutedInner({"original question": _ok_answer(document_id="doc_floor")})
        decision_maker = _MalformedDecisionMaker(malformed_on_call=1)
        engine = L4AgenticAnswerEngine(inner, decision_maker=decision_maker)

        result = engine.answer(_principal(), "original question", "manuals", _context())

        self.assertEqual(inner.calls, ["original question"])
        self.assertEqual(result["citations"][0]["document_id"], "doc_floor")

    def test_an_unrecognized_returned_value_on_a_later_call_preserves_an_earlier_good_hop(self):
        inner = _QueryRoutedInner({"query-1": _ok_answer(document_id="doc_1")})
        decision_maker = _MalformedDecisionMaker(malformed_on_call=2)
        engine = L4AgenticAnswerEngine(inner, decision_maker=decision_maker)

        result = engine.answer(_principal(), "original question", "manuals", _context())

        self.assertEqual(inner.calls, ["query-1"])
        self.assertEqual(result["citations"][0]["document_id"], "doc_1")

    def test_an_exception_from_the_inner_engine_itself_still_propagates_like_every_other_rung(self):
        # Mirrors L3CompositionAnswerEngineTest's own equivalent: only the DECISION-MAKER's output is
        # treated as untrusted here; a failure from `inner.answer()` itself (the same call every rung
        # makes) is a hard failure, not something this rung fails open on.
        class _RaisingInner:
            def answer(self, principal, query, collection_id, context):
                raise RuntimeError("boom")

        decision_maker = _ScriptedDecisionMaker([RetrieveAction("hop-1")])
        engine = L4AgenticAnswerEngine(_RaisingInner(), decision_maker=decision_maker)

        with self.assertRaises(RuntimeError):
            engine.answer(_principal(), "original question", "manuals", _context())


if __name__ == "__main__":
    unittest.main()
