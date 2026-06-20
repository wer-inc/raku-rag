from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path

from raku_rag.app import MvpSystem
from raku_rag.persistence.provider_config_audit import ProviderConfigAuditRepository

ROOT = Path(__file__).resolve().parents[2]


def load_answer_service_module():
    path = ROOT / "apps/answer-service/server.py"
    spec = importlib.util.spec_from_file_location("answer_service_server_audit", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class ProviderConfigAuditTest(unittest.TestCase):
    def test_repository_records_redacted_before_after_snapshots(self) -> None:
        repo = ProviderConfigAuditRepository()

        event = repo.record_change(
            tenant_id="tenant_a",
            event_type="provider_policy_changed",
            actor="ops@example.com",
            before={
                "provider_policy_id": "default",
                "api_key": "sk-ABCDEFGHIJKLMNOP",
                "contact": "alice@example.com",
            },
            after={
                "provider_policy_id": "default",
                "provider_regions": {"azure_document_intelligence": "us-east-1"},
                "credential_token": "secret-ABCDEFGHIJKLMNOP",
            },
            reason="approved by alice@example.com",
            correlation_id="default",
        )
        payload = json.dumps(event.to_dict(), sort_keys=True)

        self.assertEqual(event.redacted_before["provider_policy_id"], "default")
        self.assertNotIn("ops@example.com", payload)
        self.assertNotIn("alice@example.com", payload)
        self.assertNotIn("sk-ABCDEFGHIJKLMNOP", payload)
        self.assertNotIn("secret-ABCDEFGHIJKLMNOP", payload)
        self.assertIn("[REDACTED:email]", payload)
        self.assertIn("[REDACTED:secret]", payload)

    def test_answer_service_audits_parser_model_retrieval_and_logging_policy_changes(self) -> None:
        module = load_answer_service_module()
        store = module._AdminSettingsStore(MvpSystem())

        parser = store.upsert_resource(
            "tenant_a",
            "provider-policies",
            "default",
            {
                "parser_mode": "azure_document_intelligence_allowed",
                "allowed_parser_providers": ["aws_textract", "azure_document_intelligence"],
                "reason": "parser trial for alice@example.com",
            },
            actor="ops@example.com",
        )
        query_model = store.upsert_resource(
            "tenant_a",
            "query-profiles",
            "default",
            {"llm_model": "anthropic.claude-sonnet-4-6", "reason": "model upgrade"},
            actor="ops",
        )
        retrieval = store.upsert_resource(
            "tenant_a",
            "retrieval-profiles",
            "default",
            {"rerank_model": "cohere.rerank-v3-5:0", "reason": "rerank tuning"},
            actor="ops",
        )
        logging = store.upsert_resource(
            "tenant_a",
            "logging-policies",
            "default",
            {"raw_user_query_storage": "redacted", "reason": "privacy review alice@example.com"},
            actor="ops",
        )

        self.assertEqual(parser["audit_events"][-1]["event_type"], "parser_provider_changed")
        self.assertEqual(query_model["audit_events"][-1]["event_type"], "model_changed")
        self.assertEqual(retrieval["audit_events"][-1]["event_type"], "retrieval_profile_changed")
        self.assertEqual(logging["audit_events"][-1]["event_type"], "logging_policy_changed")
        self.assertIn("redacted_before", parser["audit_events"][-1])
        self.assertIn("redacted_after", parser["audit_events"][-1])
        self.assertNotIn(
            "alice@example.com", json.dumps(parser["audit_events"][-1], sort_keys=True)
        )
        self.assertNotIn("ops@example.com", json.dumps(parser["audit_events"][-1], sort_keys=True))

        parser_events = store.list_audit_events("tenant_a", event_type="parser_provider_changed")
        all_events = store.list_audit_events("tenant_a")
        other_tenant = store.list_audit_events("tenant_b")

        self.assertEqual(len(parser_events), 1)
        self.assertEqual(parser_events[0]["correlation_id"], "default")
        self.assertEqual(len(all_events), 4)
        self.assertEqual(other_tenant, [])

    def test_answer_service_classifies_residency_and_opt_in_changes(self) -> None:
        module = load_answer_service_module()
        store = module._AdminSettingsStore(MvpSystem())

        residency = store.upsert_resource(
            "tenant_a",
            "provider-policies",
            "default",
            {"allowed_regions": ["us-east-1"], "reason": "residency update"},
            actor="ops",
        )
        opt_in = store.upsert_resource(
            "tenant_a",
            "provider-policies",
            "default",
            {"customer_opt_in_status": "granted", "reason": "contract approved"},
            actor="ops",
        )

        self.assertEqual(residency["audit_events"][-1]["event_type"], "residency_override")
        self.assertEqual(opt_in["audit_events"][-1]["event_type"], "opt_in_changed")


if __name__ == "__main__":
    unittest.main()
