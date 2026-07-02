"""T051 — Scenario preview execution + S5 version trace (US3)."""

from __future__ import annotations

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

T = "tenant_phone"
ADMIN = IdentityClaims(tenant_id=T, user_id="alice", roles=("tenant_admin",))


class PricingGateway:
    def answer(self, principal, query, collection_id):
        if "料金" in query or "請求" in query:
            return {
                "status": "ok",
                "text": "スタンダードプランは月額5000円です。",
                "confidence": 0.9,
                "citations": [
                    {
                        "source_id": "faq",
                        "document_id": "FAQ-PRICING",
                        "chunk_id": "FAQ-PRICING:0",
                        "version": 1,
                        "retrieval_score": 0.9,
                        "approval_status": "approved",
                    }
                ],
                "correlation_id": "corr",
                "manufacturing": {},
            }
        return {
            "status": "insufficient_evidence",
            "text": "",
            "confidence": None,
            "citations": [],
            "correlation_id": "corr",
            "manufacturing": {},
        }


def _service() -> PhoneCallService:
    return PhoneCallService(
        PricingGateway(),
        repository=InMemoryPhoneCallRepository(),
        scenarios=PhoneScenarioService(InMemoryPhoneScenarioRepository()),
        telephony=DeterministicCallSimulator(),
        asr=DeterministicAsrProvider(),
        tts=DeterministicTtsProvider(),
    )


def _seed_billing_scenario(service: PhoneCallService) -> None:
    scenarios = service._scenarios  # noqa: SLF001 — same-composition access in tests
    scenarios.create(
        ADMIN, {"name": "請求問い合わせ", "intent": "billing", "scenario_id": "billing-basic"}
    )
    scenarios.upsert_version(
        ADMIN,
        "billing-basic",
        "scv_1",
        {
            "required_slots": [
                {"slot": "contract_id", "prompt": "ご契約番号を教えてください", "max_attempts": 2}
            ],
            "handoff_conditions": [
                {"reason": "customer_requested_human", "enabled": True},
                {"reason": "insufficient_evidence", "enabled": True},
            ],
            "fallback_message": "確認して担当者におつなぎします。",
        },
    )


class TestScenarioPreview(unittest.TestCase):
    def test_preview_runs_draft_version_without_persisting_calls(self) -> None:
        service = _service()
        _seed_billing_scenario(service)
        status, payload = service.preview_scenario(
            ADMIN,
            "billing-basic",
            "scv_1",
            {"utterances": ["請求金額について知りたい", "契約番号はC-123です"]},
        )
        self.assertEqual(status, 200)
        # Slot is asked first (contract example), then the parked question is answered.
        self.assertEqual(payload["turns"][0]["ai_action"], "ask_clarification")
        self.assertIn("契約番号", payload["turns"][0]["ai_response_text"])
        self.assertEqual(payload["turns"][1]["ai_action"], "answer_with_citations")
        self.assertFalse(payload["would_handoff"])
        # Preview never persists a call.
        _, listing = service.list_calls(ADMIN)
        self.assertEqual(listing["items"], [])

    def test_preview_reports_would_handoff(self) -> None:
        service = _service()
        _seed_billing_scenario(service)
        status, payload = service.preview_scenario(
            ADMIN, "billing-basic", "scv_1", {"utterances": ["人につないでください"]}
        )
        self.assertEqual(status, 200)
        self.assertTrue(payload["would_handoff"])

    def test_preview_requires_scenario_role(self) -> None:
        service = _service()
        _seed_billing_scenario(service)
        norole = IdentityClaims(tenant_id=T, user_id="norole", roles=())
        status, _ = service.preview_scenario(
            norole, "billing-basic", "scv_1", {"utterances": ["hi"]}
        )
        self.assertEqual(status, 403)


class TestScenarioVersionTrace(unittest.TestCase):
    def _publish(self, scenarios, version_id: str, body: dict | None = None) -> None:
        if body is not None:
            scenarios.upsert_version(ADMIN, "faq-basic", version_id, body)
        scenarios.action(ADMIN, "faq-basic", version_id, "submit-review", {})
        scenarios.action(ADMIN, "faq-basic", version_id, "approve", {})
        scenarios.action(ADMIN, "faq-basic", version_id, "publish", {})

    def test_s5_calls_record_the_version_used_and_survive_rollback(self) -> None:
        service = _service()
        scenarios = service._scenarios  # noqa: SLF001
        scenarios.create(ADMIN, {"name": "FAQ", "intent": "faq"})
        self._publish(scenarios, "scv_1")

        status, call_v1 = service.simulate_call(
            ADMIN,
            {"scenario_id": "faq-basic", "utterances": [{"type": "speech", "text": "料金は？"}]},
        )
        self.assertEqual(status, 202)

        # Publish v2, run another call, then roll back to v1.
        self._publish(scenarios, "scv_2", {"fallback_message": "v2"})
        status, call_v2 = service.simulate_call(
            ADMIN,
            {"scenario_id": "faq-basic", "utterances": [{"type": "speech", "text": "料金は？"}]},
        )
        scenario, rollback_version = scenarios.rollback(
            ADMIN, "faq-basic", {"target_version_id": "scv_1"}
        )

        _, detail_v1 = service.get_call(ADMIN, call_v1["call_id"])
        _, detail_v2 = service.get_call(ADMIN, call_v2["call_id"])
        self.assertEqual(detail_v1["scenario_version_id"], "scv_1")
        self.assertEqual(detail_v2["scenario_version_id"], "scv_2")
        # New calls run under the rollback version; old calls keep their original trace (SC-007).
        status, call_v3 = service.simulate_call(
            ADMIN,
            {"scenario_id": "faq-basic", "utterances": [{"type": "speech", "text": "料金は？"}]},
        )
        _, detail_v3 = service.get_call(ADMIN, call_v3["call_id"])
        self.assertEqual(detail_v3["scenario_version_id"], rollback_version.scenario_version_id)
        self.assertEqual(rollback_version.rollback_target_version_id, "scv_1")


if __name__ == "__main__":
    unittest.main()
