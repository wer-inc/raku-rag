"""T027 — Deterministic FAQ phone-call flow over the REAL manufacturing answer path (US1).

Covers quickstart smokes S1 (grounded FAQ answer with traceable citations), S2 (no definitive
answer without evidence), S3 (customer-requested human handoff), and S4 (call detail
traceability) — with the actual `ManufacturingSystem` (001 retrieval/ACL/groundedness + 002
safety overlay) behind the `PhoneAnswerGateway`, not a scripted fake.
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

from raku_rag.domain.models import IdentityClaims, ScopeType, SubjectType
from raku_rag.manufacturing.app import ManufacturingSystem
from raku_rag.manufacturing.domain.metadata import (
    ApprovalStatus,
    ManufacturingDocumentMetadata,
)
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
T = "tenant_phone"
ADMIN = IdentityClaims(tenant_id=T, user_id="alice", roles=("tenant_admin",))
ADMIN_OLD_ONLY = IdentityClaims(tenant_id=T, user_id="bob", roles=("tenant_admin",))
OPERATOR = IdentityClaims(tenant_id=T, user_id="op", roles=("operator",))

HOURS_TEXT = "当社の営業時間は平日9時から18時までです。土日祝日は休業です。"
OLD_PRICING_TEXT = "旧料金プランは月額3000円です。この案内は旧版です。"


def _load_server():
    path = ROOT / "apps/answer-service/server.py"
    spec = importlib.util.spec_from_file_location("answer_service_server_phone_flow", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _meta(document_id: str, status: ApprovalStatus) -> ManufacturingDocumentMetadata:
    return ManufacturingDocumentMetadata(
        tenant_id=T,
        document_id=document_id,
        approval_status=status,
        effective_date="2026-06-01" if status == ApprovalStatus.APPROVED else None,
    )


class TestPhoneCallFlow(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.srv = _load_server()
        cls.mfg = ManufacturingSystem()
        cls.mfg.grant(T, ScopeType.COLLECTION, "faq", SubjectType.USER, "alice")
        cls.mfg.ingest_manufacturing(
            tenant_id=T,
            collection_id="faq",
            document_id="FAQ-HOURS",
            text=HOURS_TEXT,
            metadata=_meta("FAQ-HOURS", ApprovalStatus.APPROVED),
        )
        # The obsolete doc is granted ONLY to bob so the "only stale evidence is visible" premise
        # holds — retrieval on this path is ACL-scoped, not collection-scoped, so a shared grant
        # would let an unrelated approved doc answer instead.
        cls.mfg.grant(T, ScopeType.COLLECTION, "old_faq", SubjectType.USER, "bob")
        cls.mfg.ingest_manufacturing(
            tenant_id=T,
            collection_id="old_faq",
            document_id="FAQ-OLD-PRICING",
            text=OLD_PRICING_TEXT,
            metadata=_meta("FAQ-OLD-PRICING", ApprovalStatus.OBSOLETE),
        )

    def setUp(self) -> None:
        srv = type(self).srv
        mfg = type(self).mfg
        self.service = PhoneCallService(
            _Gateway(srv, mfg),
            repository=InMemoryPhoneCallRepository(),
            scenarios=PhoneScenarioService(InMemoryPhoneScenarioRepository()),
            telephony=DeterministicCallSimulator(),
            asr=DeterministicAsrProvider(),
            tts=DeterministicTtsProvider(),
        )

    def _simulate(self, text: str, principal=ADMIN, **kwargs):
        body = {
            "caller": {"phone_number": "+81300001234", "customer_id": "cust_demo"},
            "collection_id": "faq",
            "utterances": [{"type": "speech", "text": text}],
        }
        body.update(kwargs)
        status, payload = self.service.simulate_call(principal, body)
        self.assertEqual(status, 202, payload)
        return payload

    def test_s1_answerable_faq_call_is_grounded_with_citations(self) -> None:
        payload = self._simulate("営業時間を教えてください")
        turn = payload["turns"][0]
        self.assertEqual(turn["ai_action"], "answer_with_citations", turn)
        self.assertTrue(turn["safety"]["answered_with_evidence"])
        self.assertIn("9時", turn["ai_response_text"])
        citation = turn["citations"][0]
        self.assertEqual(citation["document_id"], "FAQ-HOURS")
        for key in ("source_id", "chunk_id", "version", "retrieval_score"):
            self.assertIn(key, citation)
        self.assertEqual(citation["approval_status"], "approved")

    def test_s2_unsupported_question_never_asserts(self) -> None:
        payload = self._simulate("この契約で返金を確約できますか？")
        turn = payload["turns"][0]
        self.assertNotEqual(turn["ai_action"], "answer_with_citations")
        self.assertIn(turn["ai_action"], {"handoff", "ask_clarification"})
        self.assertFalse(turn["safety"]["answered_with_evidence"])
        if turn["ai_action"] == "handoff":
            self.assertIsNotNone(turn["handoff"])

    def test_obsolete_only_evidence_is_not_spoken(self) -> None:
        payload = self._simulate(
            "旧料金プランの月額はいくらですか",
            principal=ADMIN_OLD_ONLY,
            collection_id="old_faq",
        )
        turn = payload["turns"][0]
        self.assertNotEqual(turn["ai_action"], "answer_with_citations", turn)
        self.assertFalse(turn["safety"]["answered_with_evidence"])

    def test_s3_customer_requested_human_hands_off_within_one_turn(self) -> None:
        payload = self._simulate("人につないでください")
        turn = payload["turns"][0]
        self.assertEqual(turn["ai_action"], "handoff")
        self.assertEqual(turn["handoff"]["reason"], "customer_requested_human")
        # The AI response does not refuse the request.
        self.assertIn("つなぎ", turn["ai_response_text"])

        status, package = self.service.get_handoff(
            OPERATOR, turn["handoff"]["handoff_package_id"]
        )
        self.assertEqual(status, 200)
        self.assertTrue(package["summary"])
        self.assertTrue(package["transcript_excerpt_redacted"])
        self.assertTrue(package["destination_id"])

        status, accepted = self.service.accept_handoff(
            OPERATOR, turn["handoff"]["handoff_package_id"], {"operator_id": "op"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(accepted["status"], "accepted")
        status, detail = self.service.get_call(ADMIN, payload["call_id"])
        self.assertEqual(detail["state"], "transferred")

    def test_s4_call_detail_is_traceable_and_redacted(self) -> None:
        payload = self._simulate("営業時間を教えてください")
        status, detail = self.service.get_call(ADMIN, payload["call_id"])
        self.assertEqual(status, 200)
        self.assertTrue(detail["correlation_id"])
        self.assertEqual(detail["caller_phone_number_masked"], "+81******1234")
        self.assertNotIn("+81300001234", repr(detail))
        transcript = detail["transcript"]
        speakers = {t["speaker"] for t in transcript}
        self.assertIn("caller", speakers)
        self.assertIn("ai", speakers)
        ai_turn = [t for t in transcript if t["speaker"] == "ai"][0]
        self.assertTrue(ai_turn["citations"])
        self.assertIn("latency_ms", ai_turn)

    def test_multi_turn_call_keeps_sequence(self) -> None:
        payload = self._simulate("営業時間を教えてください")
        call_id = payload["call_id"]
        status, turn2 = self.service.submit_turn(
            ADMIN,
            call_id,
            {"event_type": "speech", "text": "人につないでください"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(turn2["ai_action"], "handoff")
        _, detail = self.service.get_call(ADMIN, call_id)
        sequence = [t["sequence_no"] for t in detail["transcript"]]
        self.assertEqual(sequence, sorted(sequence))
        # The handoff package carries the citations from the earlier grounded answer (FR-028).
        status, package = self.service.get_handoff(
            OPERATOR, turn2["handoff"]["handoff_package_id"]
        )
        self.assertEqual(status, 200)
        self.assertTrue(package["citations"])


class _Gateway:
    """PhoneAnswerGateway over the real ManufacturingSystem + deployed JSON serializer."""

    def __init__(self, srv, mfg) -> None:
        self._srv = srv
        self._mfg = mfg

    def answer(self, principal, query, collection_id):
        return self._srv._manufacturing_answer_json(
            self._mfg.answer(principal, query, collection_id)
        )


if __name__ == "__main__":
    unittest.main()
