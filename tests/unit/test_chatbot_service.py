import unittest

from raku_rag.chatbot import ChatbotService
from raku_rag.domain.models import IdentityClaims
from raku_rag.persistence.chatbot import InMemoryChatbotSourcePolicyRepository


def _principal(tenant="tenant_a", user="alice", roles=()):
    return IdentityClaims(tenant_id=tenant, user_id=user, roles=tuple(roles))


def _rag_ok(_principal, _query, _collection_id):
    return {
        "status": "ok",
        "text": "根拠に基づく回答です。",
        "citations": [
            {
                "kind": "text",
                "document_id": "doc_1",
                "chunk_id": "doc_1:0",
                "source_id": "src",
                "version": 1,
                "retrieval_score": 0.91,
            }
        ],
        "confidence": 0.88,
        "correlation_id": "trace_rag",
    }


def _rag_insufficient(_principal, _query, _collection_id):
    return {
        "status": "insufficient_evidence",
        "text": None,
        "citations": [],
        "confidence": None,
        "correlation_id": "trace_none",
    }


def _rag_should_not_run(_principal, _query, _collection_id):
    raise AssertionError("RAG answerer must not run without a pre-RAG ChatBot source scope")


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


class ChatbotServiceTest(unittest.TestCase):
    def test_grounded_rag_answer_returns_citations(self):
        service = ChatbotService(_rag_ok)
        _enable_internal_chat_collection(service)
        status, created = service.create_session(_principal(), {"channel": "web_chat"})
        self.assertEqual(status, 201)

        status, turn = service.submit_message(
            _principal(),
            created["session_id"],
            {"message": "料金を教えてください", "collection_id": "manuals"},
        )

        self.assertEqual(status, 200)
        self.assertEqual(turn["assistant_message"]["ai_action"], "answer_with_citations")
        self.assertTrue(turn["rag"]["answerable"])
        self.assertEqual(turn["assistant_message"]["citations"][0]["document_id"], "doc_1")

    def test_details_quick_reply_uses_previous_answer_context_for_rag(self):
        queries = []

        def rag_answerer(_principal, query, _collection_id):
            queries.append(query)
            if len(queries) == 1:
                return _rag_answer(
                    text="モータ M8 は端子台 25 N・m、基礎ボルト M16 は 95 N・m です。",
                    document_id="eq-motor-m8-torque",
                )
            return _rag_answer(
                text="結論: 同じ根拠に基づき、端子台と基礎ボルトを分けて確認します。",
                document_id="eq-motor-m8-torque",
            )

        service = ChatbotService(rag_answerer)
        _enable_internal_chat_collection(service)
        _, created = service.create_session(_principal(), {"channel": "web_chat"})

        _, first_turn = service.submit_message(
            _principal(),
            created["session_id"],
            {
                "message": "モータ M8 の締付トルクを教えて",
                "collection_id": "manuals",
            },
        )
        self.assertEqual(
            first_turn["assistant_message"]["quick_replies"][0],
            {"label": "もう少し詳しく", "value": "details"},
        )

        status, details_turn = service.submit_message(
            _principal(),
            created["session_id"],
            {"message": "details", "collection_id": "manuals"},
        )

        self.assertEqual(status, 200)
        self.assertEqual(details_turn["assistant_message"]["ai_action"], "answer_with_citations")
        self.assertTrue(details_turn["rag"]["answerable"])
        self.assertEqual(
            details_turn["assistant_message"]["citations"][0]["document_id"],
            "eq-motor-m8-torque",
        )
        self.assertNotEqual(queries[-1], "details")
        self.assertIn("モータ M8 の締付トルク", queries[-1])
        self.assertIn("eq-motor-m8-torque", queries[-1])
        self.assertEqual(
            service.get_session(_principal(), created["session_id"])[1]["messages"][-2][
                "content_redacted"
            ],
            "もう少し詳しく",
        )

    def test_rag_citation_without_chatbot_source_policy_fails_closed(self):
        service = ChatbotService(_rag_ok)
        _, created = service.create_session(_principal(), {"channel": "web_chat"})

        status, turn = service.submit_message(
            _principal(),
            created["session_id"],
            {"message": "料金を教えてください", "collection_id": "manuals"},
        )

        self.assertEqual(status, 200)
        self.assertEqual(turn["assistant_message"]["ai_action"], "handoff")
        self.assertFalse(turn["rag"]["answerable"])
        self.assertEqual(turn["rag"]["no_answer_reason"], "source_not_enabled_for_chatbot")

    def test_source_specific_policy_fails_closed_before_rag(self):
        service = ChatbotService(_rag_should_not_run)
        status, _ = service.upsert_source_policy(
            _principal(roles=("tenant_admin",)),
            "pol_src_only",
            {
                "source_id": "src",
                "collection_id": "manuals",
                "exposure_mode": "internal_authenticated",
                "allowed_channels": ["web_chat"],
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(service._source_policies[("tenant_a", "pol_src_only")]["status"], "draft")
        _, created = service.create_session(_principal(), {"channel": "web_chat"})

        status, turn = service.submit_message(
            _principal(),
            created["session_id"],
            {"message": "料金を教えてください", "collection_id": "manuals"},
        )

        self.assertEqual(status, 200)
        self.assertEqual(turn["assistant_message"]["ai_action"], "handoff")
        self.assertFalse(turn["rag"]["answerable"])
        self.assertEqual(turn["rag"]["no_answer_reason"], "source_not_enabled_for_chatbot")
        self.assertIsNone(turn["rag"]["trace_id"])

    def test_repository_backed_policy_survives_service_recreation(self):
        repo = InMemoryChatbotSourcePolicyRepository()
        service = ChatbotService(_rag_ok, source_policy_repository=repo)
        _enable_internal_chat_collection(service)

        restarted = ChatbotService(_rag_ok, source_policy_repository=repo)
        _, created = restarted.create_session(_principal(), {"channel": "web_chat"})

        status, turn = restarted.submit_message(
            _principal(),
            created["session_id"],
            {"message": "ナレッジの使い方を教えてください", "collection_id": "manuals"},
        )

        self.assertEqual(status, 200)
        self.assertEqual(turn["assistant_message"]["ai_action"], "answer_with_citations")
        self.assertEqual(turn["rag"]["source_policy_id"], "pol_collection")

    def test_rag_question_policy_allows_specific_rag_question_intents(self):
        service = ChatbotService(_rag_ok)
        service.upsert_source_policy(
            _principal(roles=("tenant_admin",)),
            "pol_rag_questions",
            {
                "source_id": "",
                "collection_id": "manuals",
                "exposure_mode": "internal_authenticated",
                "allowed_channels": ["web_chat"],
                "allowed_intents": ["rag_question"],
            },
        )
        _, created = service.create_session(_principal(), {"channel": "web_chat"})

        status, turn = service.submit_message(
            _principal(),
            created["session_id"],
            {"message": "料金を教えてください", "collection_id": "manuals"},
        )

        self.assertEqual(status, 200)
        self.assertEqual(turn["assistant_message"]["ai_action"], "answer_with_citations")

    def test_insufficient_evidence_creates_handoff_without_asserting_answer(self):
        service = ChatbotService(_rag_insufficient)
        _enable_internal_chat_collection(service)
        _, created = service.create_session(_principal(), {})

        status, turn = service.submit_message(
            _principal(),
            created["session_id"],
            {"message": "特別割引できますか", "collection_id": "manuals"},
        )

        self.assertEqual(status, 200)
        self.assertEqual(turn["assistant_message"]["ai_action"], "handoff")
        self.assertFalse(turn["rag"]["answerable"])
        self.assertEqual(turn["handoff"]["reason"], "insufficient_evidence")

    def test_cancel_scenario_collects_slots_then_creates_idempotent_ticket(self):
        service = ChatbotService(_rag_ok)
        _, created = service.create_session(_principal(), {"initial_message": "解約したい"})
        session_id = created["session_id"]
        self.assertEqual(created["assistant_message"]["ai_action"], "collect_slot")

        _, email_turn = service.submit_message(
            _principal(), session_id, {"message": "メールは user@example.com です"}
        )
        self.assertEqual(email_turn["state"]["collected_slots"]["email"], "u***@example.com")
        self.assertIn("company_name", email_turn["state"]["missing_slots"])

        _, company_turn = service.submit_message(
            _principal(), session_id, {"message": "会社名はABC株式会社です"}
        )
        self.assertEqual(company_turn["assistant_message"]["ai_action"], "confirm_action")

        _, ticket_turn = service.submit_message(_principal(), session_id, {"message": "進める"})
        self.assertEqual(ticket_turn["assistant_message"]["ai_action"], "ticket_created")
        self.assertEqual(ticket_turn["ticket"]["status"], "created")
        self.assertTrue(ticket_turn["ticket"]["idempotency_key"].endswith(":cancel_subscription"))

    def test_scenario_version_update_review_publish_and_immutable(self):
        service = ChatbotService(_rag_ok)
        admin = _principal(roles=("tenant_admin",))

        status, updated = service.upsert_scenario_version(
            admin,
            "cancel-basic",
            "csv_1",
            {
                "steps": [
                    {"id": "identify_customer", "required_slots": ["email", "company_name"]},
                    {"id": "confirm_final", "required_slots": ["final_confirmation"]},
                ],
                "rag_policy": {"collection_id": "manuals"},
                "handoff_conditions": [{"reason": "insufficient_evidence", "enabled": True}],
            },
        )
        self.assertEqual(status, 200)
        version = next(v for v in updated["versions"] if v["version_id"] == "csv_1")
        self.assertEqual(version["status"], "draft")
        self.assertEqual(version["required_slots"], ["email", "company_name", "final_confirmation"])

        status, _ = service.scenario_action(admin, "cancel-basic", "csv_1", "submit-review", {})
        self.assertEqual(status, 200)
        status, _ = service.scenario_action(admin, "cancel-basic", "csv_1", "approve", {})
        self.assertEqual(status, 200)
        status, published = service.scenario_action(admin, "cancel-basic", "csv_1", "publish", {})
        self.assertEqual(status, 200)
        self.assertEqual(published["active_version_id"], "csv_1")

        status, payload = service.upsert_scenario_version(
            admin,
            "cancel-basic",
            "csv_1",
            {"steps": [{"id": "changed"}]},
        )
        self.assertEqual(status, 409)
        self.assertEqual(payload["error"], "scenario_version_immutable")

    def test_scenario_publish_requires_approved_version(self):
        service = ChatbotService(_rag_ok)
        admin = _principal(roles=("tenant_admin",))
        service.upsert_scenario_version(
            admin, "cancel-basic", "csv_2", {"required_slots": ["email"]}
        )

        status, payload = service.scenario_action(admin, "cancel-basic", "csv_2", "publish", {})

        self.assertEqual(status, 409)
        self.assertEqual(payload["error"], "scenario_version_not_approved")

    def test_tenant_cannot_read_other_tenant_session(self):
        service = ChatbotService(_rag_ok)
        _, created = service.create_session(_principal("tenant_a", "alice"), {})

        status, payload = service.get_session(
            _principal("tenant_b", "mallory"), created["session_id"]
        )

        self.assertEqual(status, 404)
        self.assertEqual(payload["error"], "not_found")

    def test_source_exposure_policy_validation_requires_public_scope_for_anonymous(self):
        service = ChatbotService(_rag_ok)

        status, payload = service.validate_source_policy(
            _principal(roles=("tenant_admin",)),
            {"exposure_mode": "external_anonymous", "required_document_tags": []},
        )

        self.assertEqual(status, 200)
        self.assertFalse(payload["allowed"])
        self.assertIn("external_anonymous_requires_public_document_tag", payload["reasons"])

    def test_source_policy_validation_rejects_source_level_until_rag_filter_exists(self):
        service = ChatbotService(_rag_ok)

        status, payload = service.validate_source_policy(
            _principal(roles=("tenant_admin",)),
            {
                "source_id": "src",
                "collection_id": "manuals",
                "exposure_mode": "internal_authenticated",
            },
        )

        self.assertEqual(status, 200)
        self.assertFalse(payload["allowed"])
        self.assertIn("source_level_filter_requires_rag_adapter_support", payload["reasons"])

    def test_source_policy_management_requires_admin_role(self):
        service = ChatbotService(_rag_ok)

        status, payload = service.upsert_source_policy(
            _principal(roles=("field_user",)),
            "pol_denied",
            {
                "source_id": "",
                "collection_id": "manuals",
                "exposure_mode": "internal_authenticated",
            },
        )

        self.assertEqual(status, 403)
        self.assertEqual(payload["error"], "chat_role_required")

    def test_metrics_requires_ops_role(self):
        service = ChatbotService(_rag_ok)

        status, payload = service.metrics(_principal(roles=("field_user",)))

        self.assertEqual(status, 403)
        self.assertEqual(payload["error"], "chat_role_required")

    def test_scenario_publish_requires_approver_role(self):
        service = ChatbotService(_rag_ok)
        admin = _principal(roles=("tenant_admin",))
        service.create_scenario(admin, {"scenario_id": "demo", "version_id": "v1"})
        service.scenario_action(admin, "demo", "v1", "submit-review", {})
        service.scenario_action(admin, "demo", "v1", "approve", {})

        status, payload = service.scenario_action(
            _principal(roles=("scenario_admin",)), "demo", "v1", "publish", {}
        )

        self.assertEqual(status, 403)
        self.assertEqual(payload["error"], "chat_role_required")

    def test_public_widget_requires_domain_allowed_source_policy(self):
        service = ChatbotService(_rag_ok)
        admin = _principal(roles=("tenant_admin",))
        status, _ = service.upsert_source_policy(
            admin,
            "pol_public",
            {
                "source_id": "",
                "collection_id": "manuals",
                "exposure_mode": "external_anonymous",
                "allowed_channels": ["public_widget"],
                "required_document_tags": ["public_chat"],
                "allowed_domains": ["https://example.com"],
            },
        )
        self.assertEqual(status, 200)
        public_principal = _principal(user="anonymous:widget_1", roles=("chat_anonymous",))
        _, created = service.create_session(
            public_principal,
            {
                "channel": "public_widget",
                "collection_id": "manuals",
                "metadata": {
                    "chat_mode": "external_anonymous",
                    "widget_origin": "https://example.com",
                },
            },
        )

        status, turn = service.submit_message(
            public_principal,
            created["session_id"],
            {"message": "料金を教えてください", "collection_id": "manuals"},
        )

        self.assertEqual(status, 200)
        self.assertEqual(turn["assistant_message"]["ai_action"], "answer_with_citations")

    def test_public_widget_domain_mismatch_fails_closed_before_rag(self):
        service = ChatbotService(_rag_should_not_run)
        admin = _principal(roles=("tenant_admin",))
        service.upsert_source_policy(
            admin,
            "pol_public",
            {
                "source_id": "",
                "collection_id": "manuals",
                "exposure_mode": "external_anonymous",
                "allowed_channels": ["public_widget"],
                "required_document_tags": ["public_chat"],
                "allowed_domains": ["https://example.com"],
            },
        )
        public_principal = _principal(user="anonymous:widget_1", roles=("chat_anonymous",))
        _, created = service.create_session(
            public_principal,
            {
                "channel": "public_widget",
                "collection_id": "manuals",
                "metadata": {
                    "chat_mode": "external_anonymous",
                    "widget_origin": "https://evil.example",
                },
            },
        )

        status, turn = service.submit_message(
            public_principal,
            created["session_id"],
            {"message": "料金を教えてください", "collection_id": "manuals"},
        )

        self.assertEqual(status, 200)
        self.assertEqual(turn["assistant_message"]["ai_action"], "handoff")
        self.assertEqual(turn["rag"]["no_answer_reason"], "source_not_enabled_for_chatbot")


if __name__ == "__main__":
    unittest.main()
