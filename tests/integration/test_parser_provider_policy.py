from __future__ import annotations

import unittest

from workers.ingest.provider_policy import ProviderPolicy, ProviderPolicyViolation
from workers.ingest.providers.parsers import (
    AzureDocumentIntelligenceParserAdapter,
    CustomerManagedParserAdapter,
    GoogleDocumentAIParserAdapter,
    ProviderPolicyParserRouter,
    TEXT,
    PDF,
    TextractParserAdapter,
)


class FakeParserClient:
    def __init__(self, text: str) -> None:
        self.text = text
        self.calls: list[tuple[bytes, str]] = []

    def parse(self, raw: bytes, content_type: str):
        self.calls.append((raw, content_type))
        return {"text": self.text}


class ParserProviderPolicyIntegrationTest(unittest.TestCase):
    def test_default_aws_only_policy_denies_azure_before_raw_send_and_uses_customer_fallback(
        self,
    ) -> None:
        azure_client = FakeParserClient("azure should not see this")
        router = ProviderPolicyParserRouter(
            [
                CustomerManagedParserAdapter(),
                AzureDocumentIntelligenceParserAdapter(client=azure_client),
            ]
        )
        raw = b"RAW customer alice@example.com sk-abcdefghijklmnop"

        result = router.parse(
            raw,
            TEXT,
            requested_provider="azure_document_intelligence",
            policy=ProviderPolicy(tenant_id="tenant_a"),
        )
        serialized_audit = str([event.to_dict() for event in result.audit_events])

        self.assertEqual(azure_client.calls, [])
        self.assertTrue(result.fallback_used)
        self.assertEqual(result.effective_provider, "customer_managed")
        self.assertIn("RAW customer", result.parsed.text)
        self.assertNotIn("alice@example.com", serialized_audit)
        self.assertNotIn("sk-abcdefghijklmnop", serialized_audit)
        self.assertTrue(any(not event.allowed for event in result.audit_events))

    def test_azure_document_intelligence_requires_opt_in_region_zero_retention_and_no_train(
        self,
    ) -> None:
        azure_client = FakeParserClient("Azure parsed layout text")
        router = ProviderPolicyParserRouter(
            [
                CustomerManagedParserAdapter(),
                AzureDocumentIntelligenceParserAdapter(
                    client=azure_client,
                    region="eastus",
                    zero_retention=True,
                    no_train=True,
                ),
            ]
        )
        policy = ProviderPolicy(
            tenant_id="tenant_a",
            parser_mode="azure_document_intelligence_allowed",
            allowed_parser_providers=("azure_document_intelligence", "customer_managed"),
            allowed_regions=("eastus",),
            cross_cloud_processing_allowed=True,
            customer_opt_in_status="granted",
        )

        result = router.parse(
            b"%PDF raw bytes",
            PDF,
            requested_provider="azure_document_intelligence",
            policy=policy,
        )

        self.assertFalse(result.fallback_used)
        self.assertEqual(result.effective_provider, "azure_document_intelligence")
        self.assertEqual(result.parsed.text, "Azure parsed layout text")
        self.assertEqual(len(azure_client.calls), 1)
        self.assertTrue(any(event.raw_content_sent for event in result.audit_events))

    def test_azure_without_no_train_capability_falls_back_before_raw_send(self) -> None:
        azure_client = FakeParserClient("azure should not see this")
        router = ProviderPolicyParserRouter(
            [
                CustomerManagedParserAdapter(),
                AzureDocumentIntelligenceParserAdapter(client=azure_client),
            ]
        )
        policy = ProviderPolicy(
            tenant_id="tenant_a",
            parser_mode="azure_document_intelligence_allowed",
            allowed_parser_providers=("azure_document_intelligence", "customer_managed"),
            cross_cloud_processing_allowed=True,
            customer_opt_in_status="granted",
        )

        result = router.parse(
            b"fallback text",
            TEXT,
            requested_provider="azure_document_intelligence",
            policy=policy,
        )

        self.assertEqual(azure_client.calls, [])
        self.assertTrue(result.fallback_used)
        self.assertIn("zero-retention", " ".join(result.decision.reasons))
        self.assertIn("no-train", " ".join(result.decision.reasons))

    def test_google_document_ai_residency_violation_falls_back_before_raw_send(self) -> None:
        google_client = FakeParserClient("google should not see this")
        router = ProviderPolicyParserRouter(
            [
                CustomerManagedParserAdapter(),
                GoogleDocumentAIParserAdapter(
                    client=google_client,
                    region="us",
                    zero_retention=True,
                    no_train=True,
                ),
            ]
        )
        policy = ProviderPolicy(
            tenant_id="tenant_a",
            parser_mode="google_document_ai_allowed",
            allowed_parser_providers=("google_document_ai", "customer_managed"),
            allowed_regions=("asia-northeast1", "customer"),
            cross_cloud_processing_allowed=True,
            customer_opt_in_status="granted",
        )

        result = router.parse(
            b"fallback text",
            TEXT,
            requested_provider="google_document_ai",
            policy=policy,
        )

        self.assertEqual(google_client.calls, [])
        self.assertEqual(result.effective_provider, "customer_managed")
        self.assertIn("outside allowed provider regions", " ".join(result.decision.reasons))

    def test_textract_is_aws_only_path_when_customer_opt_in_is_granted(self) -> None:
        textract_client = FakeParserClient("Textract parsed PDF")
        router = ProviderPolicyParserRouter(
            [CustomerManagedParserAdapter(), TextractParserAdapter(client=textract_client)]
        )
        policy = ProviderPolicy(
            tenant_id="tenant_a",
            allowed_parser_providers=("aws_textract", "customer_managed"),
            allowed_regions=("ap-northeast-1",),
            customer_opt_in_status="granted",
        )

        result = router.parse(
            b"%PDF raw bytes",
            PDF,
            requested_provider="aws_textract",
            policy=policy,
        )

        self.assertFalse(result.fallback_used)
        self.assertEqual(result.effective_provider, "aws_textract")
        self.assertEqual(result.parsed.text, "Textract parsed PDF")
        self.assertEqual(len(textract_client.calls), 1)

    def test_no_allowed_fallback_raises_policy_violation_without_external_send(self) -> None:
        azure_client = FakeParserClient("azure should not see this")
        router = ProviderPolicyParserRouter(
            [AzureDocumentIntelligenceParserAdapter(client=azure_client)]
        )

        with self.assertRaises(ProviderPolicyViolation):
            router.parse(
                b"raw",
                TEXT,
                requested_provider="azure_document_intelligence",
                policy=ProviderPolicy(
                    tenant_id="tenant_a",
                    allowed_parser_providers=("azure_document_intelligence",),
                ),
            )

        self.assertEqual(azure_client.calls, [])


if __name__ == "__main__":
    unittest.main()
