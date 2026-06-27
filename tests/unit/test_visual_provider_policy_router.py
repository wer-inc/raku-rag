from __future__ import annotations

import unittest

from raku_rag.domain.models import BoundingBox, LayoutRegion, OcrTextRegion
from workers.ingest.provider_policy import ProviderPolicy, ProviderPolicyViolation
from workers.ingest.providers.visual import (
    OcrPolicyRouter,
    StaticProviderPolicyResolver,
    VisualEmbeddingPolicyRouter,
    VlmPolicyRouter,
)


class FakeOcr:
    provider_id = "aws_textract"
    provider_family = "aws"
    region = "ap-northeast-1"
    zero_retention = True
    no_train = True

    def __init__(self) -> None:
        self.calls = 0

    def extract(self, image: bytes, **kwargs):
        self.calls += 1
        return (OcrTextRegion("AL-42", 1.0, BoundingBox(0, 0, 1, 0.1)),)


class FakeVlm:
    provider_id = "bedrock"
    provider_family = "aws"
    region = "ap-northeast-1"
    zero_retention = True
    no_train = True
    model = "fake"

    def __init__(self) -> None:
        self.calls = 0

    def generate(self, query: str, *, visual_regions):
        self.calls += 1
        return visual_regions[0].ocr_text


class FakeVisualEmbedder:
    provider_id = "bedrock"
    provider_family = "aws"
    region = "ap-northeast-1"
    zero_retention = True
    no_train = True
    model_version = "bedrock"

    def __init__(self) -> None:
        self.calls = 0

    def embed(self, regions):
        self.calls += 1
        return [[1.0, 0.0] for _ in regions]


class VisualProviderPolicyRouterTest(unittest.TestCase):
    def test_ocr_router_denies_before_raw_bytes_leave_provider_boundary(self) -> None:
        inner = FakeOcr()
        router = OcrPolicyRouter(
            inner,
            policy_resolver=StaticProviderPolicyResolver(
                ProviderPolicy(
                    tenant_id="tenant_a",
                    allowed_ocr_providers=(),
                    customer_opt_in_status="granted",
                )
            ),
        )

        with self.assertRaises(ProviderPolicyViolation):
            router.extract(
                b"raw-image",
                tenant_id="tenant_a",
                collection_id="manuals",
                document_id="doc_img",
            )

        self.assertEqual(inner.calls, 0)
        self.assertFalse(router.audit_events[0].allowed)
        self.assertFalse(router.audit_events[0].raw_content_sent)

    def test_vlm_router_allows_granted_bedrock_policy(self) -> None:
        inner = FakeVlm()
        router = VlmPolicyRouter(
            inner,
            policy_resolver=StaticProviderPolicyResolver(
                ProviderPolicy(tenant_id="tenant_a", customer_opt_in_status="granted")
            ),
        )
        region = LayoutRegion(
            tenant_id="tenant_a",
            collection_id="manuals",
            document_id="doc_img",
            asset_id="asset_1",
            region_id="region_1",
            bbox=BoundingBox(0, 0, 1, 1),
            ocr_text="Alarm AL-42",
        )

        answer = router.generate(
            "what alarm?",
            visual_regions=(region,),
            tenant_id="tenant_a",
            collection_id="manuals",
            document_id="doc_img",
        )

        self.assertEqual(answer, "Alarm AL-42")
        self.assertEqual(inner.calls, 1)
        self.assertTrue(router.audit_events[-1].raw_content_sent)

    def test_visual_embedding_router_denies_before_embedding_call(self) -> None:
        inner = FakeVisualEmbedder()
        router = VisualEmbeddingPolicyRouter(
            inner,
            policy_resolver=StaticProviderPolicyResolver(
                ProviderPolicy(
                    tenant_id="tenant_a",
                    allowed_visual_embedding_providers=(),
                    customer_opt_in_status="granted",
                )
            ),
        )

        with self.assertRaises(ProviderPolicyViolation):
            router.embed((b"region",), tenant_id="tenant_a", collection_id="manuals")

        self.assertEqual(inner.calls, 0)


if __name__ == "__main__":
    unittest.main()
