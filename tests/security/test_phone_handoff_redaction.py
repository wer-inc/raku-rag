"""T042 — Handoff packages expose only masked/redacted caller data (SC-005, Tier A)."""

from __future__ import annotations

import json
import unittest

from raku_rag.domain.models import IdentityClaims
from raku_rag.persistence.phone_models import (
    InMemoryPhoneCallRepository,
    InMemoryPhoneScenarioRepository,
)
from raku_rag.phone.orchestrator import PhoneCallService
from raku_rag.phone.scenarios import PhoneScenarioService
from raku_rag.providers.asr import DeterministicAsrProvider
from raku_rag.providers.telephony import DeterministicCallSimulator
from raku_rag.providers.tts import DeterministicTtsProvider

ADMIN = IdentityClaims(tenant_id="tenant_a", user_id="alice", roles=("tenant_admin",))
OPERATOR = IdentityClaims(tenant_id="tenant_a", user_id="op", roles=("operator",))

RAW_PHONE = "+81300001234"
SPOKEN_PHONE = "09012345678"
CARD = "4111 1111 1111 1111"
SECRET = "sk-abcdefghijklmnop"  # pragma: allowlist secret -- redaction-test fixture


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


def _service():
    return PhoneCallService(
        InsufficientGateway(),
        repository=InMemoryPhoneCallRepository(),
        scenarios=PhoneScenarioService(InMemoryPhoneScenarioRepository()),
        telephony=DeterministicCallSimulator(),
        asr=DeterministicAsrProvider(),
        tts=DeterministicTtsProvider(),
    )


class TestHandoffPackageRedaction(unittest.TestCase):
    def test_package_has_no_raw_phone_card_or_secret(self) -> None:
        service = _service()
        status, payload = service.simulate_call(
            ADMIN,
            {
                "caller": {"phone_number": RAW_PHONE, "customer_id": "cust_1"},
                "utterances": [
                    {
                        "type": "speech",
                        "text": (
                            f"折り返しは{SPOKEN_PHONE}へ。カードは{CARD}、鍵は{SECRET}です。"
                            "返金条件を教えてください。"
                        ),
                    }
                ],
            },
        )
        self.assertEqual(status, 202)
        handoff = payload["turns"][-1].get("handoff")
        self.assertIsNotNone(handoff, "insufficient evidence must create a handoff")

        status, package = service.get_handoff(OPERATOR, handoff["handoff_package_id"])
        self.assertEqual(status, 200)
        blob = json.dumps(package, ensure_ascii=False, default=str)
        self.assertNotIn(RAW_PHONE, blob)
        self.assertNotIn(SPOKEN_PHONE, blob)
        self.assertNotIn(CARD, blob)
        self.assertNotIn(SECRET, blob)
        # Masked identity is still available to the operator.
        self.assertEqual(package["customer"]["phone_number_masked"], "+81******1234")
        self.assertTrue(package["transcript_excerpt_redacted"])

    def test_confirmed_slots_are_redacted(self) -> None:
        service = _service()
        scenarios = service._scenarios  # noqa: SLF001 — same-composition access in tests
        scenarios.create(ADMIN, {"name": "FAQ", "intent": "faq"})
        scenarios.upsert_version(
            ADMIN,
            "faq-basic",
            "scv_1",
            {"required_slots": [{"slot": "callback_number", "prompt": "折り返し番号をどうぞ"}]},
        )
        scenarios.action(ADMIN, "faq-basic", "scv_1", "submit-review", {})
        scenarios.action(ADMIN, "faq-basic", "scv_1", "approve", {})
        scenarios.action(ADMIN, "faq-basic", "scv_1", "publish", {})

        status, payload = service.simulate_call(
            ADMIN,
            {
                "caller": {"phone_number": RAW_PHONE},
                "scenario_id": "faq-basic",
                "utterances": [
                    {"type": "speech", "text": "返金条件を教えてください"},
                    {"type": "speech", "text": SPOKEN_PHONE},
                ],
            },
        )
        self.assertEqual(status, 202)
        handoff = payload["turns"][-1].get("handoff")
        self.assertIsNotNone(handoff)
        status, package = service.get_handoff(OPERATOR, handoff["handoff_package_id"])
        blob = json.dumps(package, ensure_ascii=False, default=str)
        self.assertNotIn(SPOKEN_PHONE, blob)


if __name__ == "__main__":
    unittest.main()
