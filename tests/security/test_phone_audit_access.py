"""T065 — FR-035: access to transcripts, customer identifiers, handoff packages, and QA
reviews is itself audited (who viewed what, when)."""

from __future__ import annotations

import unittest

from raku_rag.domain.models import IdentityClaims
from raku_rag.manufacturing.domain.audit import InMemoryAuditLogWriter
from raku_rag.persistence.phone_models import (
    InMemoryPhoneCallRepository,
    InMemoryPhoneQualityRepository,
    InMemoryPhoneScenarioRepository,
)
from raku_rag.phone.orchestrator import PhoneCallService
from raku_rag.phone.quality import PhoneQualityService
from raku_rag.phone.scenarios import PhoneScenarioService
from raku_rag.providers.asr import DeterministicAsrProvider
from raku_rag.providers.telephony import DeterministicCallSimulator
from raku_rag.providers.tts import DeterministicTtsProvider

ADMIN = IdentityClaims(tenant_id="tenant_a", user_id="alice", roles=("tenant_admin",))
QA = IdentityClaims(tenant_id="tenant_a", user_id="misaki", roles=("qa_reviewer",))
OPERATOR = IdentityClaims(tenant_id="tenant_a", user_id="op1", roles=("operator",))
NOROLE = IdentityClaims(tenant_id="tenant_a", user_id="norole", roles=())


class InsufficientGateway:
    def answer(self, principal, query, collection_id):
        return {
            "status": "insufficient_evidence", "text": "", "confidence": None,
            "citations": [], "correlation_id": "corr", "manufacturing": {},
        }


class PhoneAuditAccessTest(unittest.TestCase):
    def setUp(self) -> None:
        self.audit = InMemoryAuditLogWriter()
        self.service = PhoneCallService(
            InsufficientGateway(),
            repository=InMemoryPhoneCallRepository(),
            scenarios=PhoneScenarioService(InMemoryPhoneScenarioRepository()),
            telephony=DeterministicCallSimulator(),
            asr=DeterministicAsrProvider(),
            tts=DeterministicTtsProvider(),
            quality=PhoneQualityService(InMemoryPhoneQualityRepository(), audit=self.audit),
            audit=self.audit,
        )
        _, payload = self.service.simulate_call(
            ADMIN,
            {
                "caller": {"phone_number": "+81300001234"},
                "utterances": [{"type": "speech", "text": "担当者につないでください"}],
            },
        )
        self.call_id = payload["call_id"]

    def _entries(self, action: str):
        return [e for e in self.audit.read_all(ADMIN) if e.action == action]

    def test_transcript_read_is_audited_with_actor(self) -> None:
        status, _ = self.service.get_call(QA, self.call_id)
        self.assertEqual(status, 200)
        views = self._entries("phone.transcript_viewed")
        self.assertEqual(len(views), 1)
        self.assertEqual(views[0].actor_id, "misaki")
        self.assertEqual(views[0].resource_id, self.call_id)

    def test_denied_transcript_read_is_not_audited_as_view(self) -> None:
        status, _ = self.service.get_call(NOROLE, self.call_id)
        self.assertEqual(status, 403)
        self.assertEqual(self._entries("phone.transcript_viewed"), [])

    def test_handoff_package_read_is_audited(self) -> None:
        _, detail = self.service.get_call(ADMIN, self.call_id)
        handoff_id = detail["handoff"]["handoff_package_id"]
        status, _ = self.service.get_handoff(OPERATOR, handoff_id)
        self.assertEqual(status, 200)
        views = self._entries("phone.handoff_viewed")
        self.assertEqual(len(views), 1)
        self.assertEqual(views[0].actor_id, "op1")
        self.assertEqual(views[0].resource_id, handoff_id)

    def test_qa_review_write_and_read_are_audited(self) -> None:
        status, _ = self.service.create_quality_evaluation(
            QA, self.call_id, {"answer_correctness": 4}
        )
        self.assertEqual(status, 201)
        self.assertEqual(len(self._entries("phone.quality_evaluated")), 1)
        status, _ = self.service.list_quality_evaluations(QA, self.call_id)
        self.assertEqual(status, 200)
        reads = self._entries("phone.qa_reviews_viewed")
        self.assertEqual(len(reads), 1)
        self.assertEqual(reads[0].actor_id, "misaki")

    def test_audit_entries_never_carry_transcript_text(self) -> None:
        self.service.get_call(ADMIN, self.call_id)
        for entry in self.audit.read_all(ADMIN):
            self.assertNotIn("担当者につないで", repr(entry))
            self.assertNotIn("+81300001234", repr(entry))


if __name__ == "__main__":
    unittest.main()
