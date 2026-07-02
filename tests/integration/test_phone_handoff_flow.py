"""T040 — Handoff package creation + fail-closed fallback over the real answer path (US2)."""

from __future__ import annotations

import unittest

from raku_rag.domain.models import IdentityClaims
from raku_rag.persistence.phone_models import (
    InMemoryPhoneCallRepository,
    InMemoryPhoneScenarioRepository,
)
from raku_rag.phone.domain import HandoffPackage
from raku_rag.phone.handoff import HandoffService
from raku_rag.phone.interfaces import HandoffDispatchResult
from raku_rag.phone.orchestrator import PhoneCallService
from raku_rag.phone.scenarios import PhoneScenarioService
from raku_rag.providers.asr import DeterministicAsrProvider
from raku_rag.providers.telephony import DeterministicCallSimulator
from raku_rag.providers.tts import DeterministicTtsProvider

T = "tenant_phone"
ADMIN = IdentityClaims(tenant_id=T, user_id="alice", roles=("tenant_admin",))
OPERATOR = IdentityClaims(tenant_id=T, user_id="op", roles=("operator",))


class InsufficientGateway:
    def answer(self, principal, query, collection_id):
        return {
            "status": "insufficient_evidence",
            "text": "",
            "confidence": None,
            "citations": [],
            "correlation_id": "corr",
            "manufacturing": {},
        }


class UnavailableDispatch:
    name = "unavailable-queue"

    def dispatch(self, package: HandoffPackage) -> HandoffDispatchResult:
        return HandoffDispatchResult(status="unavailable", failure_reason="after_hours")


def _service(handoff: HandoffService | None = None) -> PhoneCallService:
    return PhoneCallService(
        InsufficientGateway(),
        repository=InMemoryPhoneCallRepository(),
        scenarios=PhoneScenarioService(InMemoryPhoneScenarioRepository()),
        telephony=DeterministicCallSimulator(),
        asr=DeterministicAsrProvider(),
        tts=DeterministicTtsProvider(),
        handoff=handoff,
    )


def _simulate(service, text: str):
    status, payload = service.simulate_call(
        ADMIN,
        {
            "caller": {"phone_number": "+81300001234", "customer_id": "cust_1"},
            "utterances": [{"type": "speech", "text": text}],
        },
    )
    assert status == 202, payload
    return payload


class TestHandoffFlow(unittest.TestCase):
    def test_insufficient_evidence_creates_full_package(self) -> None:
        service = _service()
        payload = _simulate(service, "未登録の返金条件について教えてください")
        turn = payload["turns"][0]
        self.assertEqual(turn["ai_action"], "handoff")
        handoff_id = turn["handoff"]["handoff_package_id"]

        status, package = service.get_handoff(OPERATOR, handoff_id)
        self.assertEqual(status, 200)
        self.assertEqual(package["reason"], "insufficient_evidence")
        self.assertEqual(package["status"], "queued")
        self.assertTrue(package["summary"])
        self.assertTrue(package["transcript_excerpt_redacted"])
        self.assertTrue(package["recommended_next_action"])
        self.assertEqual(package["customer"]["customer_id"], "cust_1")

    def test_repeated_triggers_reuse_one_package_per_call(self) -> None:
        service = _service()
        payload = _simulate(service, "人につないでください")
        first = payload["turns"][0]["handoff"]["handoff_package_id"]
        status, turn2 = service.submit_turn(
            ADMIN, payload["call_id"], {"event_type": "speech", "text": "人につないでください"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(turn2["handoff"]["handoff_package_id"], first)

    def test_accept_moves_call_to_transferred(self) -> None:
        service = _service()
        payload = _simulate(service, "人につないでください")
        handoff_id = payload["turns"][0]["handoff"]["handoff_package_id"]
        status, accepted = service.accept_handoff(
            OPERATOR, handoff_id, {"operator_id": "op", "queue_id": "general-support"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(accepted["status"], "accepted")
        _, detail = service.get_call(ADMIN, payload["call_id"])
        self.assertEqual(detail["state"], "transferred")
        self.assertEqual(detail["resolution_status"], "transferred")

    def test_unavailable_destination_falls_back_to_callback(self) -> None:
        # FR-030: when the live queue is unavailable, the caller gets a callback outcome, not
        # a dead end.
        service = _service(HandoffService(provider=UnavailableDispatch()))
        payload = _simulate(service, "人につないでください")
        handoff = payload["turns"][0]["handoff"]
        self.assertEqual(handoff["status"], "callback_requested")

    def test_provider_failure_event_fails_closed_to_human_path(self) -> None:
        service = _service()
        payload = _simulate(service, "営業時間を教えてください")  # insufficient → handoff exists
        call_id = payload["call_id"]
        status, turn = service.submit_turn(
            ADMIN, call_id, {"event_type": "provider_failure", "failed_provider": "rag"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(turn["ai_action"], "handoff")
        self.assertTrue(turn["ai_response_text"])  # never silent (SC-008)


if __name__ == "__main__":
    unittest.main()
