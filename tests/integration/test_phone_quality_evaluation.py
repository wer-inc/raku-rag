"""T064 — QA reviews persist, validate, and feed the audit-derived improvement queue (022 US4)."""

from __future__ import annotations

import unittest

from raku_rag.domain.models import IdentityClaims
from raku_rag.manufacturing.api.improvements import ImprovementQueueService
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
NOROLE = IdentityClaims(tenant_id="tenant_a", user_id="norole", roles=())


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


class PhoneQualityEvaluationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.audit = InMemoryAuditLogWriter()
        self.quality_repo = InMemoryPhoneQualityRepository()
        self.service = PhoneCallService(
            InsufficientGateway(),
            repository=InMemoryPhoneCallRepository(),
            scenarios=PhoneScenarioService(InMemoryPhoneScenarioRepository()),
            telephony=DeterministicCallSimulator(),
            asr=DeterministicAsrProvider(),
            tts=DeterministicTtsProvider(),
            quality=PhoneQualityService(self.quality_repo, audit=self.audit),
            audit=self.audit,
        )
        _, payload = self.service.simulate_call(
            ADMIN, {"utterances": [{"type": "speech", "text": "未登録の返金条件について"}]}
        )
        self.call_id = payload["call_id"]

    def _evaluate(self, body: dict, principal=QA):
        return self.service.create_quality_evaluation(principal, self.call_id, body)

    def test_evaluation_persists_and_links_improvement(self) -> None:
        status, payload = self._evaluate(
            {
                "answer_correctness": 3,
                "tone_score": 4,
                "handoff_appropriateness": 5,
                "hallucination_detected": True,
                "suggested_fix": "返金条件FAQを追加",
                "knowledge_gap_topics": ["返金条件"],
            }
        )
        self.assertEqual(status, 201, payload)
        self.assertTrue(payload["evaluation_id"].startswith("eval_"))
        self.assertTrue(payload["improvement_item_id"].startswith("imp_"))
        status, listing = self.service.list_quality_evaluations(QA, self.call_id)
        self.assertEqual(status, 200)
        self.assertEqual(len(listing["items"]), 1)

    def test_flagged_reviews_surface_in_improvement_queue(self) -> None:
        self._evaluate({"hallucination_detected": True, "knowledge_gap_topics": ["返金条件"]})
        queue = ImprovementQueueService(self.audit).list_items(ADMIN)
        phone_items = [i for i in queue.items if i.kind == "phone_qa"]
        self.assertEqual(len(phone_items), 1)
        self.assertEqual(phone_items[0].answer_id, self.call_id)
        self.assertEqual(phone_items[0].reason, "hallucination")

    def test_plain_review_is_audited_but_not_queued(self) -> None:
        status, _ = self._evaluate({"answer_correctness": 5, "tone_score": 5})
        self.assertEqual(status, 201)
        queue = ImprovementQueueService(self.audit).list_items(ADMIN)
        self.assertEqual([i for i in queue.items if i.kind == "phone_qa"], [])

    def test_hallucination_requires_fix_or_topics(self) -> None:
        status, payload = self._evaluate({"hallucination_detected": True})
        self.assertEqual(status, 422)
        self.assertEqual(payload["error"], "hallucination_requires_fix_or_topics")

    def test_score_bounds(self) -> None:
        status, payload = self._evaluate({"answer_correctness": 9})
        self.assertEqual(status, 422)
        self.assertEqual(payload["error"], "invalid_score")

    def test_role_gate_and_unknown_call(self) -> None:
        status, _ = self._evaluate({"answer_correctness": 3}, principal=NOROLE)
        self.assertEqual(status, 403)
        status, _ = self.service.create_quality_evaluation(QA, "call_missing", {})
        self.assertEqual(status, 404)

    def test_metrics_include_gap_topics_and_handoff_rate(self) -> None:
        self._evaluate({"knowledge_gap_topics": ["返金条件"]})
        status, metrics = self.service.metrics(ADMIN)
        self.assertEqual(status, 200)
        self.assertEqual(metrics["summary"]["call_count"], 1)
        self.assertEqual(metrics["summary"]["handoff_rate"], 1.0)
        topics = {t["key"] for t in metrics["knowledge_gap_topics"]}
        self.assertIn("返金条件", topics)

    def test_metrics_role_gate(self) -> None:
        status, _ = self.service.metrics(QA)
        self.assertEqual(status, 403)


if __name__ == "__main__":
    unittest.main()
