"""T026 — Orchestrator turn decisions: grounded answer, insufficient/stale evidence, barge-in,
low ASR confidence, DTMF, provider failure (US1)."""

from __future__ import annotations

import unittest

from raku_rag.domain.models import IdentityClaims
from raku_rag.persistence.phone_models import (
    InMemoryPhoneCallRepository,
    InMemoryPhoneScenarioRepository,
)
from raku_rag.phone.orchestrator import PhoneCallService, classify_intent
from raku_rag.phone.scenarios import PhoneScenarioService
from raku_rag.providers.asr import DeterministicAsrProvider
from raku_rag.providers.telephony import DeterministicCallSimulator
from raku_rag.providers.tts import DeterministicTtsProvider

ADMIN = IdentityClaims(tenant_id="tenant_a", user_id="alice", roles=("tenant_admin",))

_APPROVED_CITATION = {
    "source_id": "faq",
    "document_id": "FAQ-HOURS",
    "chunk_id": "FAQ-HOURS:0",
    "version": 3,
    "retrieval_score": 0.91,
    "approval_status": "approved",
    "effective_date": "2026-06-01",
}

_OBSOLETE_CITATION = {
    "source_id": "faq",
    "document_id": "FAQ-OLD-PRICING",
    "chunk_id": "FAQ-OLD-PRICING:0",
    "version": 1,
    "retrieval_score": 0.7,
    "approval_status": "obsolete",
}


class ScriptedGateway:
    """Keyword-scripted deterministic RAG gateway."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def answer(self, principal, query, collection_id):
        self.calls.append(query)
        if "営業時間" in query:
            return {
                "status": "ok",
                "text": "本日の営業時間は9時から18時です。",
                "confidence": 0.91,
                "citations": [dict(_APPROVED_CITATION)],
                "correlation_id": "corr_rag_1",
                "manufacturing": {},
            }
        if "旧料金" in query:
            return {
                "status": "ok",
                "text": "旧料金プランは月額3000円です。",
                "confidence": 0.7,
                "citations": [dict(_OBSOLETE_CITATION)],
                "correlation_id": "corr_rag_2",
                "manufacturing": {},
            }
        if "爆発" in query:
            raise RuntimeError("llm down")
        return {
            "status": "insufficient_evidence",
            "text": "",
            "confidence": None,
            "citations": [],
            "correlation_id": "corr_rag_3",
            "manufacturing": {},
        }


def _service():
    gateway = ScriptedGateway()
    service = PhoneCallService(
        gateway,
        repository=InMemoryPhoneCallRepository(),
        scenarios=PhoneScenarioService(InMemoryPhoneScenarioRepository()),
        telephony=DeterministicCallSimulator(),
        asr=DeterministicAsrProvider(),
        tts=DeterministicTtsProvider(),
    )
    return service, gateway


def _start(service, **kwargs):
    body = {
        "caller": {"phone_number": "+81300001234", "customer_id": "cust_1"},
        "utterances": [],
    }
    body.update(kwargs)
    status, payload = service.simulate_call(ADMIN, body)
    assert status == 202, payload
    return payload


class TestGroundedAnswer(unittest.TestCase):
    def test_answer_with_citations_carries_trace_fields(self) -> None:
        service, _ = _service()
        call_id = _start(service)["call_id"]
        status, payload = service.submit_turn(
            ADMIN, call_id, {"event_type": "speech", "text": "営業時間を教えてください"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["ai_action"], "answer_with_citations")
        self.assertTrue(payload["safety"]["answered_with_evidence"])
        citation = payload["citations"][0]
        for key in ("source_id", "document_id", "chunk_id", "version", "retrieval_score"):
            self.assertIn(key, citation)
        self.assertEqual(citation["document_id"], "FAQ-HOURS")
        self.assertTrue(payload["tts_audio_ref"].startswith("deterministic://tts/"))

    def test_insufficient_evidence_never_asserts(self) -> None:
        service, _ = _service()
        call_id = _start(service)["call_id"]
        status, payload = service.submit_turn(
            ADMIN, call_id, {"event_type": "speech", "text": "未登録の仕様について教えて"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["ai_action"], "handoff")
        self.assertFalse(payload["safety"]["answered_with_evidence"])
        self.assertEqual(payload["handoff"]["reason"], "insufficient_evidence")

    def test_stale_obsolete_evidence_is_not_spoken(self) -> None:
        service, _ = _service()
        call_id = _start(service)["call_id"]
        status, payload = service.submit_turn(
            ADMIN, call_id, {"event_type": "speech", "text": "旧料金について教えて"}
        )
        self.assertEqual(status, 200)
        self.assertNotEqual(payload["ai_action"], "answer_with_citations")
        self.assertEqual(payload["safety"]["blocked_reason"], "stale_or_unapproved_evidence")

    def test_gateway_exception_fails_closed_to_handoff(self) -> None:
        service, _ = _service()
        call_id = _start(service)["call_id"]
        status, payload = service.submit_turn(
            ADMIN, call_id, {"event_type": "speech", "text": "爆発について"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["ai_action"], "handoff")
        self.assertEqual(payload["handoff"]["reason"], "provider_failure")


class TestTurnMechanics(unittest.TestCase):
    def test_terminal_call_rejects_turns(self) -> None:
        service, _ = _service()
        call_id = _start(service)["call_id"]
        service.submit_turn(ADMIN, call_id, {"event_type": "hangup"})
        status, payload = service.submit_turn(
            ADMIN, call_id, {"event_type": "speech", "text": "もしもし"}
        )
        self.assertEqual(status, 409)
        self.assertEqual(payload["error"], "call_terminal")

    def test_barge_in_is_recorded_and_caller_input_wins(self) -> None:
        service, gateway = _service()
        call_id = _start(service)["call_id"]
        service.submit_turn(
            ADMIN, call_id, {"event_type": "speech", "text": "旧料金について教えて"}
        )
        status, payload = service.submit_turn(
            ADMIN, call_id, {"event_type": "barge_in", "text": "営業時間を教えてください"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["ai_action"], "answer_with_citations")
        _, detail = service.get_call(ADMIN, call_id)
        caller_turns = [t for t in detail["transcript"] if t["speaker"] == "caller"]
        self.assertTrue(any(t.get("barge_in") for t in caller_turns))

    def test_low_asr_confidence_reasks_then_hands_off(self) -> None:
        service, gateway = _service()
        call_id = _start(service)["call_id"]
        status, payload = service.submit_turn(
            ADMIN, call_id, {"event_type": "speech", "text": "えー", "asr_confidence": 0.2}
        )
        self.assertEqual(payload["ai_action"], "ask_clarification")
        status, payload = service.submit_turn(
            ADMIN, call_id, {"event_type": "speech", "text": "あの", "asr_confidence": 0.2}
        )
        self.assertEqual(payload["ai_action"], "handoff")
        self.assertEqual(payload["handoff"]["reason"], "low_asr_confidence")
        # The garbled audio never reached RAG.
        self.assertEqual(gateway.calls, [])

    def test_dtmf_is_acknowledged_without_rag(self) -> None:
        service, gateway = _service()
        call_id = _start(service)["call_id"]
        status, payload = service.submit_turn(
            ADMIN, call_id, {"event_type": "dtmf", "dtmf_digits": "1"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["ai_action"], "ask_clarification")
        self.assertEqual(gateway.calls, [])

    def test_hold_and_resume(self) -> None:
        service, _ = _service()
        call_id = _start(service)["call_id"]
        status, payload = service.submit_turn(ADMIN, call_id, {"event_type": "hold"})
        self.assertEqual(payload["call_state"], "on_hold")
        status, payload = service.submit_turn(ADMIN, call_id, {"event_type": "resume"})
        self.assertEqual(payload["call_state"], "active")

    def test_provider_failure_asr_falls_back_without_silence(self) -> None:
        service, _ = _service()
        call_id = _start(service)["call_id"]
        status, payload = service.submit_turn(
            ADMIN, call_id, {"event_type": "provider_failure", "failed_provider": "asr"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["ai_action"], "fallback")
        self.assertTrue(payload["ai_response_text"])

    def test_provider_failure_llm_hands_off(self) -> None:
        service, _ = _service()
        call_id = _start(service)["call_id"]
        status, payload = service.submit_turn(
            ADMIN, call_id, {"event_type": "provider_failure", "failed_provider": "llm"}
        )
        self.assertEqual(payload["ai_action"], "handoff")
        self.assertEqual(payload["handoff"]["reason"], "provider_failure")

    def test_latency_map_is_recorded_on_ai_turns(self) -> None:
        service, _ = _service()
        call_id = _start(service)["call_id"]
        service.submit_turn(
            ADMIN, call_id, {"event_type": "speech", "text": "営業時間を教えてください"}
        )
        _, detail = service.get_call(ADMIN, call_id)
        ai_turns = [t for t in detail["transcript"] if t["speaker"] == "ai"]
        self.assertTrue(ai_turns)
        latency = ai_turns[-1]["latency_ms"]
        for key in ("asr", "rag", "tts", "total"):
            self.assertIn(key, latency)


class TestIntentClassification(unittest.TestCase):
    def test_phone_intents(self) -> None:
        cases = {
            "営業時間を教えてください": "business_hours",
            "料金プランについて": "pricing_plan",
            "解約したいのですが": "refund_cancellation",
            "注文の状況を確認したい": "reservation_order_status",
            "資料を送ってください": "document_request",
            "苦情があります": "complaint",
            "経理につないでください": "department_routing",
            "オペレーターお願いします": "human_handoff",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(classify_intent(text, None), expected)

    def test_default_falls_back_to_faq(self) -> None:
        self.assertEqual(classify_intent("こんにちは", None), "faq")
        self.assertEqual(classify_intent("こんにちは", "pricing_plan"), "pricing_plan")


class TestRecordingDisclosure(unittest.TestCase):
    def test_disclosure_played_only_when_recording_enabled(self) -> None:
        service, _ = _service()
        payload = _start(service, options={"recording_enabled": True})
        _, detail = service.get_call(ADMIN, payload["call_id"])
        self.assertTrue(detail["recording_enabled"])
        self.assertTrue(detail["recording_disclosure_played"])

        payload = _start(service)
        _, detail = service.get_call(ADMIN, payload["call_id"])
        self.assertFalse(detail["recording_enabled"])
        self.assertFalse(detail["recording_disclosure_played"])


if __name__ == "__main__":
    unittest.main()
