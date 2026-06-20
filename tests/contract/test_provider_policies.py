from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

from raku_rag.app import MvpSystem
from workers.ingest.provider_policy import (
    ProviderCapability,
    ProviderPolicy,
    ProviderPolicyEnforcer,
    ProviderRequest,
    capability_for,
)

ROOT = Path(__file__).resolve().parents[2]


def load_answer_service_module():
    path = ROOT / "apps/answer-service/server.py"
    spec = importlib.util.spec_from_file_location("answer_service_server", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class ProviderPolicyContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.enforcer = ProviderPolicyEnforcer()
        self.default_policy = ProviderPolicy(tenant_id="tenant_a")

    def evaluate(self, operation: str, provider: str):
        return self.enforcer.evaluate(
            self.default_policy,
            ProviderRequest(
                operation=operation,
                provider=provider,
                capability=capability_for(provider),
            ),
        )

    def test_aws_only_denies_azure_and_google_document_parsers_without_opt_in(self) -> None:
        for provider in ("azure_document_intelligence", "google_document_ai"):
            with self.subTest(provider=provider):
                decision = self.evaluate("parse", provider)

                self.assertFalse(decision.allowed)
                self.assertTrue(decision.required_opt_in)
                self.assertIn("customer opt-in is required", " ".join(decision.reasons))
                self.assertIn(decision.fallback_provider, {"aws_textract", "customer_managed"})

    def test_aws_textract_is_allowed_when_capabilities_match_and_opt_in_is_granted(self) -> None:
        policy = ProviderPolicy(tenant_id="tenant_a", customer_opt_in_status="granted")

        decision = self.enforcer.evaluate(
            policy,
            ProviderRequest(
                operation="parse",
                provider="aws_textract",
                capability=capability_for("aws_textract"),
            ),
        )

        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reasons, ())

    def test_region_zero_retention_and_no_train_fail_closed(self) -> None:
        policy = ProviderPolicy(
            tenant_id="tenant_a",
            customer_opt_in_status="granted",
            allowed_regions=("us-west-2",),
        )
        capability = ProviderCapability(
            provider="aws_textract",
            provider_family="aws",
            region="eu-central-1",
            zero_retention=False,
            no_train=False,
        )

        decision = self.enforcer.evaluate(
            policy,
            ProviderRequest(operation="parse", provider="aws_textract", capability=capability),
        )

        self.assertFalse(decision.allowed)
        self.assertIn("outside allowed provider regions", " ".join(decision.reasons))
        self.assertIn("zero-retention", " ".join(decision.reasons))
        self.assertIn("no-train", " ".join(decision.reasons))

    def test_answer_service_internal_validation_uses_provider_policy_contract(self) -> None:
        module = load_answer_service_module()
        store = module._AdminSettingsStore(MvpSystem())

        azure = store.validate_provider_policy(
            "tenant_a",
            "default",
            {"operation": "parse", "provider": "azure_document_intelligence"},
        )
        google = store.validate_provider_policy(
            "tenant_a",
            "default",
            {"operation": "parse", "provider": "google_document_ai"},
        )
        aws_default = store.validate_provider_policy(
            "tenant_a",
            "default",
            {
                "operation": "parse",
                "provider": "aws_textract",
                "capability": {"region": "us-east-1", "zero_retention": True, "no_train": True},
            },
        )

        self.assertFalse(azure["allowed"])
        self.assertFalse(google["allowed"])
        self.assertEqual(azure["fallback_provider"], "aws_textract")
        self.assertFalse(aws_default["allowed"])
        self.assertIn("customer opt-in is required", " ".join(aws_default["reasons"]))

    def test_api_surface_has_dedicated_provider_policy_controller_and_ocr_contract(self) -> None:
        controller = (ROOT / "apps/api/src/admin/provider-policies.controller.ts").read_text(
            encoding="utf-8"
        )
        service = (ROOT / "apps/api/src/provider-policy/provider-policy.service.ts").read_text(
            encoding="utf-8"
        )
        shared = (ROOT / "packages/shared/src/dto/admin-settings.ts").read_text(encoding="utf-8")

        self.assertIn('@Controller({ path: "admin/provider-policies", version: "1" })', controller)
        self.assertIn("ProviderPolicyService", service)
        self.assertIn('"ocr"', shared)
        self.assertIn("ProviderPolicyValidationResponse", shared)


if __name__ == "__main__":
    unittest.main()
