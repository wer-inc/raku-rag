from __future__ import annotations

import unittest
from dataclasses import replace

from raku_rag.app import MvpSystem
from raku_rag.core.config import Settings, settings_from_env
from raku_rag.domain.models import BoundingBox, LayoutRegion, OcrTextRegion, VisualAsset
from raku_rag.interfaces.visual import AsyncJobStatus, AsyncSubmitRequest, IngestContext
from raku_rag.providers.captioning import CaptioningResult, DeterministicCaptioningProvider
from raku_rag.providers.layout import DeterministicLayoutExtractor
from raku_rag.providers.mock.visual import FakeAsyncDocumentAnalyzer, page_with_text
from raku_rag.providers.ocr import DeterministicOcrEngine
from raku_rag.providers.visual import (
    DeterministicStructuredExtractor,
    InvokerCaptioningProvider,
    InvokerLayoutExtractor,
    InvokerOcrEngine,
    InvokerStructuredExtractor,
    InvokerVLMProvider,
    InvokerVisualEmbeddingProvider,
    captioning_from_settings,
    layout_from_settings,
    ocr_from_settings,
    structured_from_settings,
    vlm_from_settings,
    visual_embedding_from_settings,
)
from raku_rag.providers.visual_embeddings import HashingVisualEmbeddingProvider
from raku_rag.providers.vlms import ExtractiveVLMProvider
from raku_rag.services.visual import visual_chunks_from_ingestion
from raku_rag.workers import ingestion as ingestion_worker
from raku_rag.workers.ingestion import (
    IngestionExecutor,
    VisualIngestionExecutor,
    VisualIngestionResult,
)


class VisualProviderProfileTest(unittest.TestCase):
    def test_settings_from_env_parses_visual_provider_fields(self) -> None:
        settings = settings_from_env(
            {
                "RAKU_RUNTIME_PROFILE": "production",
                "RAKU_AWS_REGION": "ap-northeast-1",
                "RAKU_OCR_PROVIDER": "aws_textract",
                "RAKU_LAYOUT_PROVIDER": "aws_textract",
                "RAKU_STRUCTURED_PROVIDER": "aws_textract",
                "RAKU_VLM_PROVIDER": "bedrock",
                "RAKU_CAPTIONING_PROVIDER": "bedrock",
                "RAKU_VISUAL_EMBEDDING_PROVIDER": "titan_multimodal",
                "RAKU_VLM_MODEL_ID": "claude-vision-test",
                "RAKU_CAPTION_MODEL_ID": "claude-caption-test",
                "RAKU_TEXTRACT_REGION": "ap-northeast-1",
                "RAKU_OCR_REGION": "ap-northeast-1",
                "RAKU_VLM_REGION": "ap-northeast-1",
                "RAKU_GCP_PROJECT_ID": "gcp-project",
                "RAKU_GCP_LOCATION": "asia-northeast1",
                "RAKU_GCP_WORKLOAD_IDENTITY_PROVIDER": "projects/1/locations/global/pools/p/providers/p",
                "RAKU_GCP_WORKLOAD_IDENTITY_SA_EMAIL": "svc@example.iam.gserviceaccount.com",
                "RAKU_CROP_STORAGE_URI": "s3://visual-crops",
                "RAKU_VISUAL_EVIDENCE_PROMOTION": "true",
                "RAKU_VISUAL_EVIDENCE_VERIFIER_QUORUM": "2",
                "RAKU_VISUAL_EVIDENCE_VERIFIERS": "bedrock:claude,vertex:gemini",
                "RAKU_MAX_INLINE_OCR_BYTES": "12345",
                "RAKU_MAX_REGIONS_VERIFIED_PER_ANSWER": "4",
                "RAKU_FORCE_DETERMINISTIC": "true",
            }
        )

        self.assertEqual(settings.runtime_profile, "production")
        self.assertEqual(settings.aws_region, "ap-northeast-1")
        self.assertEqual(settings.ocr_provider, "aws_textract")
        self.assertEqual(settings.layout_provider, "aws_textract")
        self.assertEqual(settings.structured_provider, "aws_textract")
        self.assertEqual(settings.vlm_provider, "bedrock")
        self.assertEqual(settings.captioning_provider, "bedrock")
        self.assertEqual(settings.visual_embedding_provider, "titan_multimodal")
        self.assertEqual(settings.vlm_model_id, "claude-vision-test")
        self.assertEqual(settings.caption_model_id, "claude-caption-test")
        self.assertEqual(settings.textract_region, "ap-northeast-1")
        self.assertEqual(settings.ocr_region, "ap-northeast-1")
        self.assertEqual(settings.vlm_region, "ap-northeast-1")
        self.assertEqual(settings.gcp_project_id, "gcp-project")
        self.assertEqual(settings.gcp_location, "asia-northeast1")
        self.assertEqual(
            settings.gcp_workload_identity_provider,
            "projects/1/locations/global/pools/p/providers/p",
        )
        self.assertEqual(
            settings.gcp_workload_identity_sa_email,
            "svc@example.iam.gserviceaccount.com",
        )
        self.assertEqual(settings.crop_storage_uri, "s3://visual-crops")
        self.assertTrue(settings.visual_evidence_promotion)
        self.assertEqual(settings.visual_evidence_verifier_quorum, 2)
        self.assertEqual(
            settings.visual_evidence_verifier_providers,
            ("bedrock:claude", "vertex:gemini"),
        )
        self.assertEqual(settings.max_inline_ocr_bytes, 12345)
        self.assertEqual(settings.max_regions_verified_per_answer, 4)
        self.assertTrue(settings.force_deterministic)

    def test_production_without_visual_provider_stays_deterministic(self) -> None:
        settings = replace(Settings(), runtime_profile="production")

        self.assertIsInstance(ocr_from_settings(settings), DeterministicOcrEngine)
        self.assertIsInstance(layout_from_settings(settings), DeterministicLayoutExtractor)
        self.assertIsInstance(structured_from_settings(settings), DeterministicStructuredExtractor)
        self.assertIsInstance(captioning_from_settings(settings), DeterministicCaptioningProvider)
        self.assertIsInstance(vlm_from_settings(settings), ExtractiveVLMProvider)
        self.assertIsInstance(
            visual_embedding_from_settings(settings), HashingVisualEmbeddingProvider
        )

    def test_deterministic_profile_ignores_explicit_real_visual_provider(self) -> None:
        settings = replace(
            Settings(),
            ocr_provider="aws_textract",
            layout_provider="aws_textract",
            structured_provider="aws_textract",
            vlm_provider="bedrock",
            captioning_provider="bedrock",
            visual_embedding_provider="titan_multimodal",
        )

        self.assertIsInstance(ocr_from_settings(settings), DeterministicOcrEngine)
        self.assertIsInstance(layout_from_settings(settings), DeterministicLayoutExtractor)
        self.assertIsInstance(structured_from_settings(settings), DeterministicStructuredExtractor)
        self.assertIsInstance(captioning_from_settings(settings), DeterministicCaptioningProvider)
        self.assertIsInstance(vlm_from_settings(settings), ExtractiveVLMProvider)
        self.assertIsInstance(
            visual_embedding_from_settings(settings), HashingVisualEmbeddingProvider
        )

    def test_force_deterministic_overrides_explicit_production_visual_provider(self) -> None:
        settings = replace(
            Settings(),
            runtime_profile="production",
            ocr_provider="aws_textract",
            layout_provider="aws_textract",
            structured_provider="aws_textract",
            vlm_provider="bedrock",
            captioning_provider="bedrock",
            visual_embedding_provider="titan_multimodal",
            force_deterministic=True,
        )

        self.assertIsInstance(ocr_from_settings(settings), DeterministicOcrEngine)
        self.assertIsInstance(layout_from_settings(settings), DeterministicLayoutExtractor)
        self.assertIsInstance(structured_from_settings(settings), DeterministicStructuredExtractor)
        self.assertIsInstance(captioning_from_settings(settings), DeterministicCaptioningProvider)
        self.assertIsInstance(vlm_from_settings(settings), ExtractiveVLMProvider)
        self.assertIsInstance(
            visual_embedding_from_settings(settings), HashingVisualEmbeddingProvider
        )

    def test_explicit_production_visual_provider_uses_injected_invoker(self) -> None:
        settings = replace(
            Settings(),
            runtime_profile="production",
            ocr_provider="aws_textract",
            layout_provider="aws_textract",
            structured_provider="aws_textract",
            vlm_provider="bedrock",
            captioning_provider="bedrock",
            visual_embedding_provider="titan_multimodal",
        )

        ocr = ocr_from_settings(
            settings,
            invoker=lambda image: (
                OcrTextRegion("panel AL-42", 1.0, BoundingBox(0.0, 0.0, 1.0, 0.1)),
            ),
        )
        captioning = captioning_from_settings(
            settings, invoker=lambda image: CaptioningResult("succeeded", "caption")
        )
        layout = layout_from_settings(
            settings, invoker=lambda image, **kwargs: (_region("panel AL-42", page_number=1),)
        )
        structured = structured_from_settings(
            settings, invoker=lambda regions, **kwargs: {"regions": len(regions)}
        )
        vlm = vlm_from_settings(settings, invoker=lambda query, regions: regions[0].ocr_text)
        visual_embedding = visual_embedding_from_settings(
            settings, invoker=lambda regions: [[1.0, 0.0] for _ in regions]
        )

        self.assertIsInstance(ocr, InvokerOcrEngine)
        self.assertEqual(ocr.extract(b"image")[0].text, "panel AL-42")
        self.assertIsInstance(captioning, InvokerCaptioningProvider)
        self.assertEqual(captioning.caption(b"image").generated_caption_text, "caption")
        self.assertIsInstance(layout, InvokerLayoutExtractor)
        self.assertEqual(
            layout.extract(b"image", tenant_id="t", collection_id="c")[0].ocr_text,
            "panel AL-42",
        )
        self.assertIsInstance(structured, InvokerStructuredExtractor)
        self.assertEqual(
            structured.extract((_region("panel AL-42", page_number=1),)), {"regions": 1}
        )
        self.assertIsInstance(vlm, InvokerVLMProvider)
        self.assertEqual(
            vlm.generate("q", visual_regions=[_region("panel AL-42", page_number=1)]),
            "panel AL-42",
        )
        self.assertIsInstance(visual_embedding, InvokerVisualEmbeddingProvider)
        self.assertEqual(visual_embedding.embed((b"region",)), [[1.0, 0.0]])

    def test_explicit_production_visual_provider_builds_lazy_aws_adapter(self) -> None:
        settings = replace(Settings(), runtime_profile="production", ocr_provider="aws_textract")
        provider = ocr_from_settings(settings)

        self.assertEqual(getattr(provider, "provider_id", ""), "aws_textract")
        self.assertEqual(getattr(provider, "region", ""), "ap-northeast-1")

    def test_fake_async_document_analyzer_returns_neutral_analysis(self) -> None:
        analyzer = FakeAsyncDocumentAnalyzer(
            pages=(page_with_text(text="Page 2 alarm AL-42", page_number=2),)
        )
        request = AsyncSubmitRequest(
            document_ref="s3://bucket/manual.pdf",
            context=IngestContext(
                tenant_id="tenant_a",
                collection_id="manuals",
                source_id="upload",
                document_id="doc_pdf",
                content_type="application/pdf",
            ),
        )

        handle = analyzer.submit(request)
        analysis = analyzer.poll(handle)

        self.assertEqual(handle.provider, "fake_document_ai")
        self.assertEqual(analysis.status, AsyncJobStatus.SUCCEEDED)
        self.assertEqual(analysis.pages[0].page_number, 2)
        self.assertEqual(analysis.pages[0].layout_regions[0].ocr_text, "Page 2 alarm AL-42")
        self.assertEqual(analyzer.submitted, (request,))

    def test_document_analysis_can_be_assembled_into_visual_chunks(self) -> None:
        analyzer = FakeAsyncDocumentAnalyzer(
            pages=(
                page_with_text(text="Page 1 pump alarm AL-41", page_number=1),
                page_with_text(text="Page 2 pump alarm AL-42", page_number=2),
            )
        )
        request = AsyncSubmitRequest(
            document_ref="s3://bucket/manual.pdf",
            context=IngestContext("tenant_a", "manuals", "upload", "doc_pdf", "application/pdf"),
        )
        analysis = analyzer.poll(analyzer.submit(request))

        results = VisualIngestionExecutor().execute_document_analysis(
            tenant_id="tenant_a",
            collection_id="manuals",
            source_id="upload",
            document_id="doc_pdf",
            document_ref=request.document_ref,
            analysis=analysis,
        )
        chunks = tuple(
            chunk for result in results for chunk in visual_chunks_from_ingestion(result)
        )

        self.assertEqual(len(chunks), 2)
        self.assertEqual(
            {chunk.chunk_id for chunk in chunks}, {"doc_pdf:visual:1:0", "doc_pdf:visual:2:0"}
        )
        self.assertIn("AL-42", chunks[1].text)

    def test_page_aware_visual_chunk_ids_do_not_collide_across_page_results(self) -> None:
        page1 = VisualIngestionResult(
            asset=_asset("doc_pdf", page_number=1),
            regions=(_region("Page 1", page_number=1),),
            visual_vectors=((1.0,),),
            caption_status="not_requested",
        )
        page2 = VisualIngestionResult(
            asset=_asset("doc_pdf", page_number=2),
            regions=(_region("Page 2", page_number=2),),
            visual_vectors=((1.0,),),
            caption_status="not_requested",
        )

        ids = {
            visual_chunks_from_ingestion(page1)[0].chunk_id,
            visual_chunks_from_ingestion(page2)[0].chunk_id,
        }

        self.assertEqual(ids, {"doc_pdf:visual:1:0", "doc_pdf:visual:2:0"})

    def test_pdf_worker_falls_back_to_sync_page_images_when_async_s3_unavailable(self) -> None:
        system = MvpSystem()
        executor = IngestionExecutor(
            system.ingestion,
            async_document_analyzer=_FailingAsyncAnalyzer(),
        )
        original = ingestion_worker._render_all_pdf_pages
        ingestion_worker._render_all_pdf_pages = lambda raw: {
            1: b"OCR: PDF fallback page one VIS-PDF-FALLBACK\ncaption: fallback caption",
            2: b"OCR: PDF fallback page two shelf F-22\ncaption: fallback caption",
        }
        try:
            result = executor.execute_document(
                tenant_id="tenant_a",
                collection_id="manuals",
                source_id="upload",
                document_id="doc_pdf",
                raw=b"%PDF fake",
                content_type="application/pdf",
                document_ref="s3://tokyo-bucket/doc.pdf",
            )
        finally:
            ingestion_worker._render_all_pdf_pages = original

        self.assertEqual(result.status, "succeeded")
        self.assertEqual(result.async_provider, "sync_page_image_fallback")
        chunks = [chunk for chunk, _vector in system.store.iter_items()]
        self.assertEqual(
            {chunk.chunk_id for chunk in chunks},
            {"doc_pdf:visual:1:0", "doc_pdf:visual:2:0"},
        )
        self.assertTrue(all(chunk.metadata["pdf_page_fallback"] for chunk in chunks))
        self.assertIn("VIS-PDF-FALLBACK", chunks[0].text)


def _asset(document_id: str, *, page_number: int) -> VisualAsset:
    return VisualAsset(
        tenant_id="tenant_a",
        collection_id="manuals",
        document_id=document_id,
        asset_id=f"asset_p{page_number}",
        storage_uri="memory://asset",
        checksum="checksum",
        page_number=page_number,
        metadata={"visual_embedding_model_version": "test"},
    )


def _region(text: str, *, page_number: int) -> LayoutRegion:
    asset_id = f"asset_p{page_number}"
    return LayoutRegion(
        tenant_id="tenant_a",
        collection_id="manuals",
        document_id="doc_pdf",
        asset_id=asset_id,
        region_id=f"{asset_id}:region:1",
        bbox=BoundingBox(0.0, 0.0, 1.0, 0.1),
        page_number=page_number,
        region_type="text",
        ocr_text=text,
    )


class _FailingAsyncAnalyzer:
    provider_id = "aws_textract"

    def submit(self, request: AsyncSubmitRequest):
        raise RuntimeError("InvalidS3ObjectException: Unable to get object metadata from S3")


if __name__ == "__main__":
    unittest.main()
