import unittest

from raku_rag.chatbot import ChatbotService
from raku_rag.chatbot.answer_engine import DialogueContext, L0DeterministicAnswerEngine
from raku_rag.chatbot.authority import InMemoryChatbotAuthorityRepository
from raku_rag.chatbot.dialogue_manager import DialogueManager
from raku_rag.chatbot.envelope import L1EnvelopeAnswerEngine
from raku_rag.chatbot.service import ChatSession, StoredMessage
from raku_rag.domain.models import IdentityClaims


def _principal(tenant="tenant_a", user="alice", roles=()):
    return IdentityClaims(tenant_id=tenant, user_id=user, roles=tuple(roles))


def _rag_answer(text="根拠に基づく回答です。", document_id="doc_1"):
    return {
        "status": "ok",
        "text": text,
        "citations": [
            {
                "kind": "text",
                "document_id": document_id,
                "chunk_id": f"{document_id}:0",
                "source_id": "src",
                "version": 1,
                "retrieval_score": 0.91,
            }
        ],
        "confidence": 0.88,
        "correlation_id": "trace_rag",
    }


def _enable_internal_chat_collection(service: ChatbotService, principal=None):
    principal = principal or _principal(roles=("tenant_admin",))
    return service.upsert_source_policy(
        principal,
        "pol_collection",
        {
            "source_id": "",
            "collection_id": "manuals",
            "exposure_mode": "internal_authenticated",
            "allowed_channels": ["web_chat"],
        },
    )


def _no_quick_reply(_text: str) -> str | None:
    return None


class L0DeterministicAnswerEngineTest(unittest.TestCase):
    def test_answer_forwards_exactly_to_wrapped_rag_answerer_and_ignores_context(self):
        calls = []

        def rag_answerer(principal, query, collection_id):
            calls.append((principal, query, collection_id))
            return {"status": "ok", "text": "answer", "citations": []}

        engine = L0DeterministicAnswerEngine(rag_answerer)
        principal = _principal()
        context = DialogueContext(
            collection_id="manuals",
            previous_question="previous?",
            previous_answer="previous answer",
            previous_citations=({"document_id": "doc_1"},),
            previous_document_ids=("doc_1",),
            source_policy_ids=("pol_1",),
        )

        result = engine.answer(principal, "question", "manuals", context)

        self.assertEqual(result, {"status": "ok", "text": "answer", "citations": []})
        self.assertEqual(calls, [(principal, "question", "manuals")])


class DialogueManagerTest(unittest.TestCase):
    def test_last_answer_context_returns_none_without_a_grounded_answer(self):
        manager = DialogueManager()
        session = ChatSession(tenant_id="tenant_a", user_id="alice", session_id="s1")

        self.assertIsNone(manager.last_answer_context(session, _no_quick_reply))

    def test_last_answer_context_reconstructs_question_answer_and_document_ids(self):
        manager = DialogueManager()
        session = ChatSession(tenant_id="tenant_a", user_id="alice", session_id="s1")
        session.messages.append(
            StoredMessage(message_id="m1", role="user", content_redacted="AL-21の手順は？")
        )
        session.messages.append(
            StoredMessage(
                message_id="m2",
                role="assistant",
                content_redacted="結論: ...",
                ai_action="answer_with_citations",
                citations=[{"document_id": "doc_1"}],
                metadata={"source_answer_text": "raw answer", "source_question": "AL-21の手順は？"},
            )
        )

        context = manager.last_answer_context(session, _no_quick_reply)

        self.assertEqual(context["question"], "AL-21の手順は？")
        self.assertEqual(context["document_ids"], ["doc_1"])
        self.assertEqual(context["source_answer_text"], "raw answer")

    def test_build_context_defaults_when_no_prior_answer_but_carries_scope(self):
        manager = DialogueManager()
        session = ChatSession(tenant_id="tenant_a", user_id="alice", session_id="s1")

        context = manager.build_context(session, _no_quick_reply, "manuals", ["pol_1"])

        self.assertEqual(context.collection_id, "manuals")
        self.assertIsNone(context.previous_question)
        self.assertEqual(context.previous_citations, ())
        self.assertEqual(context.source_policy_ids, ("pol_1",))


class ChatbotAuthorityResolutionTest(unittest.TestCase):
    def test_resolve_answer_engine_defaults_to_l0_for_unconfigured_tenant(self):
        service = ChatbotService(lambda principal, query, collection_id: _rag_answer())

        # L1 is registered by default (P1) but must never apply to a tenant nobody dialed to it.
        self.assertIn("L1", service._answer_engines)
        engine = service._resolve_answer_engine("tenant_a")

        self.assertIsInstance(engine, L0DeterministicAnswerEngine)

    def test_resolve_answer_engine_falls_back_to_l0_for_unregistered_level(self):
        repo = InMemoryChatbotAuthorityRepository()
        repo.set("tenant_a", "L2")
        service = ChatbotService(
            lambda principal, query, collection_id: _rag_answer(),
            authority_repository=repo,
        )

        engine = service._resolve_answer_engine("tenant_a")

        self.assertIsInstance(engine, L0DeterministicAnswerEngine)

    def test_resolve_answer_engine_resolves_to_l1_only_for_a_tenant_explicitly_set(self):
        repo = InMemoryChatbotAuthorityRepository()
        repo.set("tenant_a", "L1")
        service = ChatbotService(
            lambda principal, query, collection_id: _rag_answer(),
            authority_repository=repo,
        )

        self.assertIsInstance(service._resolve_answer_engine("tenant_a"), L1EnvelopeAnswerEngine)
        self.assertIsInstance(
            service._resolve_answer_engine("tenant_b"), L0DeterministicAnswerEngine
        )


class ChatbotServiceAnswerEngineWiringTest(unittest.TestCase):
    def test_free_text_turn_routes_through_the_resolved_engine_with_populated_context(self):
        captured_contexts = []

        class SpyEngine:
            def answer(self, principal, query, collection_id, context):
                captured_contexts.append(context)
                return _rag_answer(
                    text=f"回答: {query}", document_id=f"doc_{len(captured_contexts)}"
                )

        def base_rag_answerer(principal, query, collection_id):
            raise AssertionError("must be routed through the resolved engine, not the raw callable")

        service = ChatbotService(base_rag_answerer)
        service._answer_engines["L0"] = SpyEngine()
        _enable_internal_chat_collection(service)
        _, created = service.create_session(_principal(), {"channel": "web_chat"})

        service.submit_message(
            _principal(),
            created["session_id"],
            {"message": "AL-21 の手順は？", "collection_id": "manuals"},
        )
        service.submit_message(
            _principal(),
            created["session_id"],
            {"message": "続けて教えて", "collection_id": "manuals"},
        )

        self.assertEqual(len(captured_contexts), 2)
        self.assertIsNone(captured_contexts[0].previous_question)
        self.assertEqual(captured_contexts[1].previous_question, "AL-21 の手順は？")
        self.assertEqual(captured_contexts[1].previous_document_ids, ("doc_1",))
        self.assertEqual(captured_contexts[1].collection_id, "manuals")
        self.assertEqual(captured_contexts[1].source_policy_ids, ("pol_collection",))


if __name__ == "__main__":
    unittest.main()
