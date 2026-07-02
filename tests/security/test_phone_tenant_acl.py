"""T010 — Phone tenant/ACL isolation hard gate (FR-039, Tier A).

「1箇所漏れたら全部漏れる」前提: calls, transcripts, handoff packages, and scenarios must never
cross a tenant boundary, and the RAG gateway must receive the SIGNED principal (never a body
override). Role gates deny by default.
"""

from __future__ import annotations

import unittest

from raku_rag.domain.models import IdentityClaims
from raku_rag.persistence.phone_models import (
    InMemoryPhoneCallRepository,
    InMemoryPhoneScenarioRepository,
)
from raku_rag.phone.orchestrator import PhoneCallService
from raku_rag.phone.scenarios import PhoneScenarioService, ScenarioError
from raku_rag.providers.asr import DeterministicAsrProvider
from raku_rag.providers.telephony import DeterministicCallSimulator
from raku_rag.providers.tts import DeterministicTtsProvider

TENANT_A_ADMIN = IdentityClaims(tenant_id="tenant_a", user_id="alice", roles=("tenant_admin",))
TENANT_B_ADMIN = IdentityClaims(tenant_id="tenant_b", user_id="mallory", roles=("tenant_admin",))
TENANT_A_NO_ROLE = IdentityClaims(tenant_id="tenant_a", user_id="norole", roles=())
TENANT_B_OPERATOR = IdentityClaims(tenant_id="tenant_b", user_id="op_b", roles=("operator",))


class RecordingGateway:
    """Asserts the phone layer forwards the signed principal into RAG (FR-009/FR-039)."""

    def __init__(self) -> None:
        self.principals: list[IdentityClaims] = []

    def answer(self, principal: IdentityClaims, query: str, collection_id):
        self.principals.append(principal)
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
            "correlation_id": "corr_rag",
            "manufacturing": {},
        }


def _service(gateway=None):
    gateway = gateway or RecordingGateway()
    service = PhoneCallService(
        gateway,
        repository=InMemoryPhoneCallRepository(),
        scenarios=PhoneScenarioService(InMemoryPhoneScenarioRepository()),
        telephony=DeterministicCallSimulator(),
        asr=DeterministicAsrProvider(),
        tts=DeterministicTtsProvider(),
    )
    return service, gateway


def _simulate(service, principal=TENANT_A_ADMIN, text="営業時間を教えてください"):
    status, payload = service.simulate_call(
        principal,
        {
            "caller": {"phone_number": "+81300001234", "customer_id": "cust_1"},
            "utterances": [{"type": "speech", "text": text}],
        },
    )
    assert status == 202, payload
    return payload


class TestTenantIsolation(unittest.TestCase):
    def test_call_is_not_visible_across_tenants(self) -> None:
        service, _ = _service()
        call_id = _simulate(service)["call_id"]
        status, _ = service.get_call(TENANT_B_ADMIN, call_id)
        self.assertEqual(status, 404)
        status, _ = service.get_call(TENANT_A_ADMIN, call_id)
        self.assertEqual(status, 200)

    def test_call_list_is_tenant_scoped(self) -> None:
        service, _ = _service()
        _simulate(service)
        status, payload = service.list_calls(TENANT_B_ADMIN)
        self.assertEqual(status, 200)
        self.assertEqual(payload["items"], [])
        self.assertEqual(payload["tenant_id"], "tenant_b")

    def test_turns_cannot_be_submitted_across_tenants(self) -> None:
        service, _ = _service()
        call_id = _simulate(service)["call_id"]
        status, _ = service.submit_turn(
            TENANT_B_ADMIN, call_id, {"event_type": "speech", "text": "営業時間は？"}
        )
        self.assertEqual(status, 404)

    def test_handoff_package_is_not_visible_across_tenants(self) -> None:
        service, _ = _service()
        payload = _simulate(service, text="人につないでください")
        handoff_id = payload["turns"][0]["handoff"]["handoff_package_id"]
        status, _ = service.get_handoff(TENANT_B_OPERATOR, handoff_id)
        self.assertEqual(status, 404)
        status, _ = service.accept_handoff(TENANT_B_OPERATOR, handoff_id, {"operator_id": "x"})
        self.assertEqual(status, 404)

    def test_scenarios_are_tenant_scoped(self) -> None:
        scenarios = PhoneScenarioService(InMemoryPhoneScenarioRepository())
        scenarios.create(TENANT_A_ADMIN, {"name": "FAQ", "intent": "faq"})
        self.assertEqual(scenarios.list(TENANT_B_ADMIN), [])
        with self.assertRaises(ScenarioError):
            scenarios.get(TENANT_B_ADMIN, "faq-basic")


class TestPrincipalPropagation(unittest.TestCase):
    def test_gateway_receives_signed_principal_not_body_override(self) -> None:
        service, gateway = _service()
        status, _ = service.simulate_call(
            TENANT_A_ADMIN,
            {
                # A hostile body tries to switch tenants; the phone layer must ignore it.
                "tenant_id": "tenant_b",
                "caller": {"phone_number": "+81300001234"},
                "utterances": [{"type": "speech", "text": "営業時間を教えてください"}],
            },
        )
        self.assertEqual(status, 202)
        self.assertTrue(gateway.principals)
        for principal in gateway.principals:
            self.assertEqual(principal.tenant_id, "tenant_a")
            self.assertEqual(principal.user_id, "alice")


class TestRoleDenyByDefault(unittest.TestCase):
    def test_simulate_requires_role(self) -> None:
        service, _ = _service()
        status, _ = service.simulate_call(
            TENANT_A_NO_ROLE, {"utterances": [{"type": "speech", "text": "hi"}]}
        )
        self.assertEqual(status, 403)

    def test_call_read_requires_role(self) -> None:
        service, _ = _service()
        call_id = _simulate(service)["call_id"]
        status, _ = service.get_call(TENANT_A_NO_ROLE, call_id)
        self.assertEqual(status, 403)
        status, _ = service.list_calls(TENANT_A_NO_ROLE)
        self.assertEqual(status, 403)

    def test_handoff_read_requires_role(self) -> None:
        service, _ = _service()
        payload = _simulate(service, text="人につないでください")
        handoff_id = payload["turns"][0]["handoff"]["handoff_package_id"]
        status, _ = service.get_handoff(TENANT_A_NO_ROLE, handoff_id)
        self.assertEqual(status, 403)

    def test_scenario_manage_requires_role(self) -> None:
        scenarios = PhoneScenarioService(InMemoryPhoneScenarioRepository())
        self.assertFalse(scenarios.can_manage(TENANT_A_NO_ROLE))
        self.assertFalse(scenarios.can_approve(TENANT_A_NO_ROLE))


class TestTranscriptPrivacy(unittest.TestCase):
    def test_raw_caller_number_never_in_call_detail(self) -> None:
        service, _ = _service()
        payload = _simulate(service)
        status, detail = service.get_call(TENANT_A_ADMIN, payload["call_id"])
        self.assertEqual(status, 200)
        blob = repr(detail)
        self.assertNotIn("+81300001234", blob)
        self.assertIn("+81******1234", blob)

    def test_spoken_phone_number_redacted_in_transcript(self) -> None:
        service, _ = _service()
        payload = _simulate(service, text="折り返しは09012345678までお願いします")
        status, detail = service.get_call(TENANT_A_ADMIN, payload["call_id"])
        self.assertEqual(status, 200)
        self.assertNotIn("09012345678", repr(detail))
        self.assertEqual(detail["transcript_redaction_status"], "redacted")


if __name__ == "__main__":
    unittest.main()
