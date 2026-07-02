"""T067 — Phone data lifecycle surfaces: retention read, audited export gate, real redaction
(022 FR-038/046/047, Tier A)."""

from __future__ import annotations

import os
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
OPS = IdentityClaims(tenant_id="tenant_a", user_id="dave", roles=("ops_owner",))
QA = IdentityClaims(tenant_id="tenant_a", user_id="misaki", roles=("qa_reviewer",))
NOROLE = IdentityClaims(tenant_id="tenant_a", user_id="norole", roles=())

SECRET_UTTERANCE = "折り返しは09012345678へ。返金条件を教えてください。"


class OkGateway:
    def answer(self, principal, query, collection_id):
        return {
            "status": "insufficient_evidence", "text": "", "confidence": None,
            "citations": [], "correlation_id": "corr", "manufacturing": {},
        }


class PhoneDataLifecycleTest(unittest.TestCase):
    def setUp(self) -> None:
        self.audit = InMemoryAuditLogWriter()
        self.service = PhoneCallService(
            OkGateway(),
            repository=InMemoryPhoneCallRepository(),
            scenarios=PhoneScenarioService(InMemoryPhoneScenarioRepository()),
            telephony=DeterministicCallSimulator(),
            asr=DeterministicAsrProvider(),
            tts=DeterministicTtsProvider(),
            quality=PhoneQualityService(InMemoryPhoneQualityRepository(), audit=self.audit),
            audit=self.audit,
        )
        os.environ.pop("RAKU_PHONE_EXPORT_ENABLED", None)
        _, payload = self.service.simulate_call(
            ADMIN,
            {
                "caller": {"phone_number": "+81300001234"},
                "utterances": [{"type": "speech", "text": SECRET_UTTERANCE}],
            },
        )
        self.call_id = payload["call_id"]

    def tearDown(self) -> None:
        os.environ.pop("RAKU_PHONE_EXPORT_ENABLED", None)

    def test_retention_policy_read_is_role_gated(self) -> None:
        status, policy = self.service.retention_policy(OPS)
        self.assertEqual(status, 200)
        self.assertFalse(policy["recording_enabled_default"])
        self.assertEqual(self.service.retention_policy(NOROLE)[0], 403)
        self.assertEqual(self.service.retention_policy(QA)[0], 403)

    def test_export_disabled_returns_conflict_and_is_audited(self) -> None:
        status, payload = self.service.export_calls(ADMIN, {})
        self.assertEqual(status, 409)
        self.assertEqual(payload["error"], "export_not_enabled")
        denials = [
            e for e in self.audit.read_all(ADMIN)
            if e.action == "phone.export_requested" and e.decision == "export_not_enabled"
        ]
        self.assertEqual(len(denials), 1)

    def test_export_enabled_queues_a_redacted_job(self) -> None:
        os.environ["RAKU_PHONE_EXPORT_ENABLED"] = "1"
        status, payload = self.service.export_calls(ADMIN, {})
        self.assertEqual(status, 202)
        self.assertEqual(payload["status"], "queued")
        self.assertTrue(payload["redacted"])

    def test_export_requires_lifecycle_role(self) -> None:
        self.assertEqual(self.service.export_calls(QA, {})[0], 403)

    def test_delete_request_redacts_transcript_and_handoff(self) -> None:
        status, payload = self.service.delete_call_request(
            ADMIN, self.call_id, {"mode": "redact", "reason": "customer_privacy_request"}
        )
        self.assertEqual(status, 202)
        self.assertEqual(payload["status"], "completed")

        _, detail = self.service.get_call(ADMIN, self.call_id)
        blob = repr(detail)
        self.assertNotIn("返金条件", blob)
        self.assertNotIn("5678", blob.replace("+81******1234", ""))  # spoken number gone
        self.assertEqual(detail["summary"], "")
        self.assertEqual(detail["transcript_redaction_status"], "redacted")
        # Trace identifiers survive for audit continuity.
        self.assertTrue(all(t["turn_id"] for t in detail["transcript"]))
        if detail["handoff"]:
            self.assertEqual(detail["handoff"]["transcript_excerpt_redacted"], "[削除済み]")
        audited = [
            e for e in self.audit.read_all(ADMIN) if e.action == "phone.delete_request"
        ]
        self.assertEqual(len(audited), 1)

    def test_delete_request_is_tenant_admin_or_audit_only(self) -> None:
        self.assertEqual(self.service.delete_call_request(OPS, self.call_id, {})[0], 403)
        self.assertEqual(self.service.delete_call_request(QA, self.call_id, {})[0], 403)


if __name__ == "__main__":
    unittest.main()
