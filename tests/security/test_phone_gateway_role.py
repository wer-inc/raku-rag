"""L015 — phone_gateway service-role minimality + caller-number masking (024 FR-L03/L04, Tier A).

The telephony adapter's synthesized principal may ONLY start calls and submit turns. Everything
else (call history, handoff read/accept, scenario management) must deny. And the raw caller
E.164 must never appear in what the adapter sends or what the platform stores.
"""

from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path

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

ROOT = Path(__file__).resolve().parents[2]
ADAPTER = ROOT / "infra/connect/lambda/connect_phone_adapter.py"

GATEWAY = IdentityClaims(tenant_id="tenant_a", user_id="phone-gateway", roles=("phone_gateway",))
ADMIN = IdentityClaims(tenant_id="tenant_a", user_id="alice", roles=("tenant_admin",))

RAW_CALLER = "+819012345678"


class OkGateway:
    def answer(self, principal, query, collection_id):
        return {
            "status": "ok",
            "text": "営業時間は9時から18時です。",
            "confidence": 0.9,
            "citations": [
                {
                    "source_id": "faq",
                    "document_id": "FAQ-HOURS",
                    "chunk_id": "FAQ-HOURS:0",
                    "version": 1,
                    "retrieval_score": 0.9,
                    "approval_status": "approved",
                }
            ],
            "correlation_id": "corr",
            "manufacturing": {},
        }


def _service() -> PhoneCallService:
    return PhoneCallService(
        OkGateway(),
        repository=InMemoryPhoneCallRepository(),
        scenarios=PhoneScenarioService(InMemoryPhoneScenarioRepository()),
        telephony=DeterministicCallSimulator(),
        asr=DeterministicAsrProvider(),
        tts=DeterministicTtsProvider(),
    )


class TestPhoneGatewayRoleMinimality(unittest.TestCase):
    def test_gateway_can_start_calls_and_submit_turns(self) -> None:
        service = _service()
        status, payload = service.simulate_call(
            GATEWAY,
            {
                "channel": "connect",
                "provider": "amazon-connect",
                "provider_call_id": "cf-contact-1",
                "utterances": [],
            },
        )
        self.assertEqual(status, 202)
        status, turn = service.submit_turn(
            GATEWAY, payload["call_id"], {"event_type": "speech", "text": "営業時間は？"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(turn["ai_action"], "answer_with_citations")

    def test_gateway_cannot_read_calls_or_history(self) -> None:
        service = _service()
        status, payload = service.simulate_call(GATEWAY, {"utterances": []})
        call_id = payload["call_id"]
        self.assertEqual(service.get_call(GATEWAY, call_id)[0], 403)
        self.assertEqual(service.list_calls(GATEWAY)[0], 403)

    def test_gateway_cannot_touch_handoffs(self) -> None:
        service = _service()
        _, payload = service.simulate_call(
            GATEWAY, {"utterances": [{"type": "speech", "text": "人につないでください"}]}
        )
        handoff_id = payload["turns"][-1]["handoff"]["handoff_package_id"]
        self.assertEqual(service.get_handoff(GATEWAY, handoff_id)[0], 403)
        self.assertEqual(service.accept_handoff(GATEWAY, handoff_id, {})[0], 403)

    def test_gateway_cannot_manage_scenarios(self) -> None:
        service = _service()
        self.assertEqual(service.list_scenarios(GATEWAY)[0], 403)
        self.assertEqual(service.create_scenario(GATEWAY, {"name": "x", "intent": "faq"})[0], 403)
        self.assertEqual(
            service.scenario_action(GATEWAY, "faq-basic", "scv_1", "approve", {})[0], 403
        )
        self.assertEqual(service.rollback_scenario(GATEWAY, "faq-basic", {})[0], 403)

    def test_public_facade_does_not_accept_phone_gateway(self) -> None:
        roles_ts = (ROOT / "apps/api/src/auth/roles.ts").read_text("utf-8")
        self.assertNotIn(
            "phone_gateway",
            roles_ts,
            "phone_gateway is an internal-boundary service role; the public /v1 facade must not accept it",
        )


class TestAdapterMasksCallerNumber(unittest.TestCase):
    def test_outbound_request_body_never_contains_raw_number(self) -> None:
        spec = importlib.util.spec_from_file_location("connect_adapter_sec", ADAPTER)
        adapter = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(adapter)

        captured: list[tuple[str, dict, dict]] = []

        def fake_post(path, headers, body):
            captured.append((path, dict(headers), json.loads(json.dumps(body))))
            if path.endswith("/simulate"):
                return 202, {"call_id": "call_x", "status": "active"}
            return 200, {"ai_action": "answer_with_citations", "call_state": "active"}

        adapter._post = fake_post
        adapter._cached_did_map = {
            "+815055550100": {"tenant_id": "tenant_a", "user_id": "phone-gateway", "groups": []}
        }
        event = json.loads((ROOT / "tests/fixtures/phone/connect_events.json").read_text("utf-8"))[
            "call_start"
        ]
        result = adapter.lambda_handler(event)
        self.assertEqual(result["ok"], "true")

        blob = json.dumps(captured, ensure_ascii=False)
        self.assertNotIn(RAW_CALLER, blob)
        self.assertIn("+81******5678", blob)
        # And the synthesized principal carries ONLY the service role.
        _, headers, _ = captured[0]
        self.assertEqual(json.loads(headers["x-raku-roles"]), ["phone_gateway"])


if __name__ == "__main__":
    unittest.main()
