from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

from raku_rag.app import MvpSystem
from raku_rag.services.provider_policy_runtime import provider_policy_allows
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
                "capability": {
                    "region": "ap-northeast-1",
                    "zero_retention": True,
                    "no_train": True,
                },
            },
        )

        self.assertFalse(azure["allowed"])
        self.assertFalse(google["allowed"])
        self.assertEqual(azure["fallback_provider"], "aws_textract")
        self.assertFalse(aws_default["allowed"])
        self.assertIn("customer opt-in is required", " ".join(aws_default["reasons"]))

    def test_answer_service_provider_policy_upsert_updates_runtime_repository(self) -> None:
        module = load_answer_service_module()

        class RuntimePolicyRepo:
            def __init__(self) -> None:
                self.items: dict[str, dict] = {}

            def get_mapping(
                self, tenant_id: str, collection_id: str = "", provider_policy_id: str = "default"
            ) -> dict:
                return self.items.get(
                    provider_policy_id,
                    {
                        "tenant_id": tenant_id,
                        "provider_policy_id": provider_policy_id,
                        "customer_opt_in_required": True,
                        "customer_opt_in_status": "pending",
                        "opt_in_status_by_family": {},
                    },
                )

            def list_mappings(self, tenant_id: str, collection_id: str = "") -> list[dict]:
                return list(self.items.values())

            def upsert(self, tenant_id: str, provider_policy_id: str, body: dict) -> dict:
                item = {
                    **self.get_mapping(tenant_id, "", provider_policy_id),
                    **body,
                    "tenant_id": tenant_id,
                    "provider_policy_id": provider_policy_id,
                }
                self.items[provider_policy_id] = item
                return item

        repo = RuntimePolicyRepo()
        store = module._AdminSettingsStore(MvpSystem(), provider_policy_repo=repo)

        store.upsert_resource(
            "tenant_a",
            "provider-policies",
            "default",
            {
                "customer_opt_in_status": "granted",
                "opt_in_status_by_family": {"aws": "granted"},
                "reason": "contract approved",
            },
            actor="ops",
        )
        decision = store.validate_provider_policy(
            "tenant_a",
            "default",
            {"operation": "ocr", "provider": "aws_textract"},
        )

        self.assertEqual(repo.items["default"]["customer_opt_in_status"], "granted")
        self.assertTrue(decision["allowed"], decision["reasons"])

    def test_default_capabilities_are_japan_region_and_cross_cloud_fail_closed(self) -> None:
        self.assertEqual(capability_for("aws_textract").region, "ap-northeast-1")
        self.assertEqual(capability_for("bedrock").region, "ap-northeast-1")
        self.assertEqual(capability_for("google_document_ai").region, "asia-northeast1")
        self.assertFalse(capability_for("google_document_ai").zero_retention)
        self.assertFalse(capability_for("azure_document_intelligence").no_train)

    def test_visual_operations_share_provider_policy_allowlists(self) -> None:
        policy = ProviderPolicy(
            tenant_id="tenant_a",
            customer_opt_in_status="granted",
            allowed_vlm_providers=(),
            allowed_caption_providers=("bedrock",),
            allowed_layout_providers=("aws_textract",),
            allowed_structured_providers=("aws_textract",),
            allowed_visual_embedding_providers=(),
        )

        vlm = self.enforcer.evaluate(
            policy,
            ProviderRequest(
                operation="vlm",
                provider="bedrock",
                capability=capability_for("bedrock"),
            ),
        )
        caption = self.enforcer.evaluate(
            policy,
            ProviderRequest(
                operation="caption",
                provider="bedrock",
                capability=capability_for("bedrock"),
            ),
        )
        layout = self.enforcer.evaluate(
            policy,
            ProviderRequest(
                operation="layout",
                provider="aws_textract",
                capability=capability_for("aws_textract"),
            ),
        )
        visual_embedding = self.enforcer.evaluate(
            policy,
            ProviderRequest(
                operation="visual_embedding",
                provider="bedrock",
                capability=capability_for("bedrock"),
            ),
        )

        self.assertFalse(vlm.allowed)
        self.assertIn("bedrock is not allowed for vlm", " ".join(vlm.reasons))
        self.assertTrue(caption.allowed)
        self.assertTrue(layout.allowed)
        self.assertFalse(visual_embedding.allowed)

    def test_family_specific_opt_in_can_deny_cross_cloud_vlm_before_egress(self) -> None:
        policy = ProviderPolicy(
            tenant_id="tenant_a",
            allowed_vlm_providers=("google_gemini", "customer_managed"),
            allowed_regions=("asia-northeast1",),
            cross_cloud_processing_allowed=True,
            zero_retention_required=False,
            no_train_required=False,
            customer_opt_in_status="granted",
            opt_in_status_by_family={"google": "pending"},
        )

        decision = self.enforcer.evaluate(
            policy,
            ProviderRequest(
                operation="vlm",
                provider="google_gemini",
                capability=capability_for("google_gemini"),
            ),
        )

        self.assertFalse(decision.allowed)
        self.assertIn("customer opt-in is required", " ".join(decision.reasons))

    def test_runtime_policy_guard_applies_tenant_opt_in_to_cloud_ocr_aliases(self) -> None:
        class Resolver:
            def __init__(self, policy: ProviderPolicy) -> None:
                self.policy = policy

            def get(
                self,
                tenant_id: str,
                collection_id: str = "",
                provider_policy_id: str = "default",
            ) -> ProviderPolicy:
                return self.policy

        pending = ProviderPolicy(
            tenant_id="tenant_a",
            parser_mode="google",
            allowed_ocr_providers=("google_document_ai",),
            allowed_regions=("asia-northeast1",),
            cross_cloud_processing_allowed=True,
            zero_retention_required=False,
            no_train_required=False,
            customer_opt_in_status="pending",
        )
        granted = ProviderPolicy(
            tenant_id="tenant_a",
            parser_mode="google",
            allowed_ocr_providers=("google_document_ai",),
            allowed_regions=("asia-northeast1",),
            cross_cloud_processing_allowed=True,
            zero_retention_required=False,
            no_train_required=False,
            customer_opt_in_status="granted",
        )

        self.assertFalse(
            provider_policy_allows(
                operation="ocr",
                provider="google_docai",
                policy_resolver=Resolver(pending),
                tenant_id="tenant_a",
                collection_id="manuals",
            )
        )
        self.assertTrue(
            provider_policy_allows(
                operation="ocr",
                provider="google_docai",
                policy_resolver=Resolver(granted),
                tenant_id="tenant_a",
                collection_id="manuals",
            )
        )

    def test_api_surface_has_dedicated_provider_policy_controller_and_ocr_contract(self) -> None:
        controller = (ROOT / "apps/api/src/admin/provider-policies.controller.ts").read_text(
            encoding="utf-8"
        )
        service = (ROOT / "apps/api/src/provider-policy/provider-policy.service.ts").read_text(
            encoding="utf-8"
        )
        shared = (ROOT / "packages/shared/src/dto/admin-settings.ts").read_text(encoding="utf-8")

        self.assertIn(
            '@Controller({ path: "admin/provider-policies", version: "1" })',
            controller,
        )
        self.assertIn("ProviderPolicyService", service)
        self.assertIn('"ocr"', shared)
        self.assertIn("ProviderPolicyValidationResponse", shared)


if __name__ == "__main__":
    unittest.main()
