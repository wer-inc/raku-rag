from __future__ import annotations

import io
import json
import unittest

from raku_rag.core.config import Settings
from raku_rag.domain.models import CaptionSource, ExtractionSource
from raku_rag.interfaces.visual import AsyncJobStatus, AsyncSubmitRequest, IngestContext
from raku_rag.providers.aws_visual import (
    BedrockVisionCaptioningProvider,
    TextractAsyncDocumentAnalyzer,
    TextractLayoutExtractor,
    TextractOcrEngine,
    build_bedrock_vision_invoker,
    build_textract_analyze_invoker,
)
from raku_rag.providers.visual import (
    async_document_analyzer_from_settings,
    captioning_from_settings,
    layout_from_settings,
    ocr_from_settings,
    vlm_from_settings,
)


class FakeTextractClient:
    def __init__(self) -> None:
        self.analyze_calls: list[dict] = []
        self.start_calls: list[dict] = []
        self.get_calls: list[dict] = []

    def analyze_document(self, **kwargs):
        self.analyze_calls.append(kwargs)
        return _textract_response()

    def start_document_analysis(self, **kwargs):
        self.start_calls.append(kwargs)
        return {"JobId": "job-123"}

    def get_document_analysis(self, **kwargs):
        self.get_calls.append(kwargs)
        return {"JobStatus": "SUCCEEDED", **_textract_response(page=2)}


class FakeBedrockClient:
    def __init__(self, text: str = "panel shows AL-42") -> None:
        self.text = text
        self.calls: list[dict] = []

    def invoke_model(self, *, modelId: str, body: bytes, accept: str, contentType: str):
        decoded = json.loads(body.decode("utf-8"))
        self.calls.append({"modelId": modelId, "body": decoded})
        payload = {"content": [{"type": "text", "text": self.text}]}
        return {"body": io.BytesIO(json.dumps(payload).encode("utf-8"))}


class AwsVisualProviderTest(unittest.TestCase):
    def test_textract_ocr_and_layout_normalize_line_blocks(self) -> None:
        client = FakeTextractClient()
        invoker = build_textract_analyze_invoker(client=client)
        ocr = TextractOcrEngine(region="ap-northeast-1", invoker=invoker)
        layout = TextractLayoutExtractor(region="ap-northeast-1", invoker=invoker)

        ocr_regions = ocr.extract(b"image")
        layout_regions = layout.extract(
            b"image",
            tenant_id="tenant_a",
            collection_id="manuals",
            document_id="doc_img",
            asset_id="asset_1",
            ocr_regions=ocr_regions,
        )

        self.assertEqual(client.analyze_calls[0]["Document"], {"Bytes": b"image"})
        self.assertEqual(ocr_regions[0].text, "Alarm AL-42")
        self.assertEqual(ocr_regions[0].confidence, 0.987)
        self.assertEqual(ocr_regions[0].extraction_source, ExtractionSource.AWS_TEXTRACT.value)
        self.assertEqual(layout_regions[0].region_id, "asset_1:p1:region:1")
        self.assertEqual(layout_regions[0].ocr_text, "Alarm AL-42")
        self.assertEqual(layout_regions[0].metadata["extractor_version"], "aws-textract-layout-v1")

    def test_bedrock_vision_caption_request_uses_image_block(self) -> None:
        client = FakeBedrockClient(text="Caption text")
        invoker = build_bedrock_vision_invoker(client=client)
        provider = BedrockVisionCaptioningProvider(model_id="m", invoker=invoker)

        result = provider.caption(b"png-bytes", content_type="image/png")

        self.assertEqual(result.status, "succeeded")
        self.assertEqual(result.generated_caption_text, "Caption text")
        self.assertEqual(result.caption_source, CaptionSource.BEDROCK_CLAUDE_VISION.value)
        content = client.calls[0]["body"]["messages"][0]["content"]
        self.assertEqual(content[0]["type"], "image")
        self.assertEqual(content[0]["source"]["media_type"], "image/png")
        self.assertEqual(content[1]["type"], "text")

    def test_textract_async_analyzer_submits_s3_ref_and_returns_pages(self) -> None:
        client = FakeTextractClient()
        analyzer = TextractAsyncDocumentAnalyzer(region="ap-northeast-1", client=client)
        request = AsyncSubmitRequest(
            document_ref="s3://bucket/manual.pdf",
            context=IngestContext("tenant_a", "manuals", "upload", "doc_pdf"),
        )

        handle = analyzer.submit(request)
        analysis = analyzer.poll(handle)

        self.assertEqual(handle.provider, "aws_textract")
        self.assertEqual(handle.token, "job-123")
        self.assertEqual(
            client.start_calls[0]["DocumentLocation"],
            {"S3Object": {"Bucket": "bucket", "Name": "manual.pdf"}},
        )
        self.assertEqual(client.get_calls[0]["JobId"], "job-123")
        self.assertEqual(analysis.status, AsyncJobStatus.SUCCEEDED)
        self.assertEqual(analysis.pages[0].page_number, 2)
        self.assertEqual(analysis.pages[0].ocr_regions[0].text, "Alarm AL-42")

    def test_textract_async_analyzer_collects_paginated_blocks(self) -> None:
        class PaginatedTextractClient(FakeTextractClient):
            def get_document_analysis(self, **kwargs):
                self.get_calls.append(kwargs)
                if "NextToken" not in kwargs:
                    return {
                        "JobStatus": "SUCCEEDED",
                        "NextToken": "next-1",
                        **_textract_response(page=1),
                    }
                return {"JobStatus": "SUCCEEDED", **_textract_response(page=2)}

        client = PaginatedTextractClient()
        analyzer = TextractAsyncDocumentAnalyzer(region="ap-northeast-1", client=client)
        request = AsyncSubmitRequest(
            document_ref="s3://bucket/manual.pdf",
            context=IngestContext("tenant_a", "manuals", "upload", "doc_pdf"),
        )

        analysis = analyzer.poll(analyzer.submit(request))

        self.assertEqual([call.get("NextToken") for call in client.get_calls], [None, "next-1"])
        self.assertEqual([page.page_number for page in analysis.pages], [1, 2])

    def test_production_visual_factories_select_aws_adapters_without_injected_invokers(
        self,
    ) -> None:
        settings = Settings(
            runtime_profile="production",
            ocr_provider="aws_textract",
            layout_provider="aws_textract",
            captioning_provider="bedrock",
            vlm_provider="bedrock",
        )

        self.assertIsInstance(ocr_from_settings(settings), TextractOcrEngine)
        self.assertIsInstance(layout_from_settings(settings), TextractLayoutExtractor)
        self.assertIsInstance(
            captioning_from_settings(settings),
            BedrockVisionCaptioningProvider,
        )
        self.assertIsNotNone(async_document_analyzer_from_settings(settings))
        self.assertEqual(getattr(vlm_from_settings(settings), "provider_id", ""), "bedrock")


def _textract_response(*, page: int = 1) -> dict:
    return {
        "Blocks": [
            {
                "BlockType": "LINE",
                "Text": "Alarm AL-42",
                "Confidence": 98.7,
                "Page": page,
                "Geometry": {
                    "BoundingBox": {
                        "Left": 0.1,
                        "Top": 0.2,
                        "Width": 0.3,
                        "Height": 0.04,
                    }
                },
            }
        ]
    }


if __name__ == "__main__":
    unittest.main()
