"""S1-3 — ChatBot state survives a service restart via the session/handoff/scenario repositories.

Two ChatbotService instances SHARING repositories simulate an answer-service restart: everything
written through instance A must be readable/continuable through instance B. Previously all of
this lived in per-instance dicts and a restart lost every conversation.
"""

from __future__ import annotations

import unittest

from raku_rag.chatbot import ChatbotService
from raku_rag.domain.models import IdentityClaims
from raku_rag.persistence.chatbot import (
    InMemoryChatFeedbackRepository,
    InMemoryChatHandoffRepository,
    InMemoryChatScenarioRepository,
    InMemoryChatSessionRepository,
)

USER = IdentityClaims(tenant_id="tenant_a", user_id="alice", roles=("tenant_admin",))
OTHER_TENANT = IdentityClaims(tenant_id="tenant_b", user_id="mallory", roles=("tenant_admin",))


def _answerer(principal, query, collection_id, *, intent_query=None):
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
            }
        ],
        "correlation_id": "corr",
        "manufacturing": {},
    }


class ChatbotPersistenceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.repos = {
            "session_repository": InMemoryChatSessionRepository(),
            "handoff_repository": InMemoryChatHandoffRepository(),
            "feedback_repository": InMemoryChatFeedbackRepository(),
            "scenario_repository": InMemoryChatScenarioRepository(),
        }

    def _service(self) -> ChatbotService:
        # A fresh ChatbotService over the SAME repositories = a restarted process.
        return ChatbotService(_answerer, **self.repos)

    def test_session_and_messages_survive_restart(self) -> None:
        first = self._service()
        status, created = first.create_session(
            USER, {"initial_message": "営業時間を教えてください"}
        )
        self.assertEqual(status, 201)
        session_id = created["session_id"]

        second = self._service()  # restart
        status, detail = second.get_session(USER, session_id)
        self.assertEqual(status, 200, detail)
        roles = [m["role"] for m in detail["messages"]]
        self.assertIn("user", roles)
        self.assertIn("assistant", roles)

        # The conversation CONTINUES across the restart (state machine intact).
        status, turn = second.submit_message(
            USER, session_id, {"message": "担当者につないでください"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(turn["assistant_message"]["ai_action"], "handoff")
        self.assertIsNotNone(turn["handoff"])

    def test_handoff_package_survives_restart(self) -> None:
        first = self._service()
        _, created = first.create_session(USER, {"initial_message": "担当者につないでください"})
        handoff_id = created["handoff"]["handoff_package_id"]

        second = self._service()
        status, package = second.get_handoff(
            IdentityClaims(tenant_id="tenant_a", user_id="op", roles=("operator",)), handoff_id
        )
        self.assertEqual(status, 200)
        self.assertEqual(package["reason"], "customer_requested_human")
        self.assertTrue(package["transcript"])

    def test_scenario_lifecycle_survives_restart(self) -> None:
        first = self._service()
        status, scenario = first.create_scenario(
            USER, {"name": "返品受付", "scenario_id": "returns-basic", "version_id": "v1"}
        )
        self.assertEqual(status, 201)
        first.scenario_action(USER, "returns-basic", "v1", "submit-review", {})
        first.scenario_action(USER, "returns-basic", "v1", "approve", {})
        first.scenario_action(USER, "returns-basic", "v1", "publish", {})

        second = self._service()
        status, listing = second.list_scenarios(USER)
        self.assertEqual(status, 200)
        by_id = {s["scenario_id"]: s for s in listing["items"]}
        self.assertIn("returns-basic", by_id)
        self.assertEqual(by_id["returns-basic"]["status"], "published")
        self.assertEqual(by_id["returns-basic"]["active_version_id"], "v1")
        # Seed default still listed until a tenant override exists.
        self.assertIn("cancel-basic", by_id)

    def test_list_and_metrics_survive_restart(self) -> None:
        first = self._service()
        first.create_session(USER, {"initial_message": "営業時間を教えてください"})
        first.create_session(USER, {"initial_message": "担当者につないでください"})

        second = self._service()
        status, listing = second.list_sessions(USER)
        self.assertEqual(status, 200)
        self.assertEqual(len(listing["items"]), 2)
        status, metrics = second.metrics(USER)
        self.assertEqual(status, 200)
        self.assertEqual(metrics["summary"]["conversation_count"], 2)
        self.assertGreater(metrics["summary"]["handoff_rate"], 0.0)

    def test_tenant_isolation_holds_across_repositories(self) -> None:
        first = self._service()
        _, created = first.create_session(USER, {"initial_message": "営業時間を教えてください"})
        session_id = created["session_id"]

        second = self._service()
        status, _ = second.get_session(OTHER_TENANT, session_id)
        self.assertEqual(status, 404)
        status, listing = second.list_sessions(OTHER_TENANT)
        self.assertEqual(listing["items"], [])

    def test_feedback_is_stored(self) -> None:
        first = self._service()
        _, created = first.create_session(USER, {"initial_message": "営業時間を教えてください"})
        status, feedback = first.submit_feedback(
            USER,
            created["session_id"],
            {"rating": 1, "issue_type": "rag_gap", "comment": "情報が古い"},
        )
        self.assertEqual(status, 201)
        stored = self.repos["feedback_repository"].list("tenant_a")
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0]["evaluation_id"], feedback["evaluation_id"])


if __name__ == "__main__":
    unittest.main()
