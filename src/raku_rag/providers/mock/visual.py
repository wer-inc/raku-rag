"""Deterministic visual provider fakes for PDF/visual-understanding contracts."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from typing import Sequence

from raku_rag.domain.models import (
    BoundingBox,
    CaptionSource,
    ExtractionSource,
    LayoutRegion,
    OcrTextRegion,
)
from raku_rag.interfaces.visual import (
    AsyncJobStatus,
    AsyncSubmitRequest,
    DocumentAnalysis,
    DocumentAnalysisPage,
    JobHandle,
)
from raku_rag.providers.captioning import CaptioningResult

FAKE_VISUAL_CAPABILITY = {
    "no_train": True,
    "zero_retention": True,
    "provider": "fake_visual",
}


class FakeAsyncDocumentAnalyzer:
    """Offline async analyzer that behaves like a completed provider job.

    Tests can pass neutral pages directly. If no pages are supplied, the analyzer derives one text
    region from ``request.document_ref`` so the contract remains useful without fixture files.
    """

    provider = "fake_document_ai"
    capabilities = dict(FAKE_VISUAL_CAPABILITY)

    def __init__(self, pages: Sequence[DocumentAnalysisPage] = ()) -> None:
        self._pages = tuple(pages)
        self.submitted: tuple[AsyncSubmitRequest, ...] = ()

    def submit(self, request: AsyncSubmitRequest) -> JobHandle:
        self.submitted = (*self.submitted, request)
        token = hashlib.sha256(
            f"{self.provider}:{request.context.tenant_id}:{request.document_ref}".encode("utf-8")
        ).hexdigest()[:16]
        return JobHandle(provider=self.provider, token=token, document_ref=request.document_ref)

    def poll(self, handle: JobHandle) -> DocumentAnalysis:
        pages = self._pages or (_page_from_text(handle.document_ref, page_number=1),)
        return DocumentAnalysis(
            provider=self.provider,
            job_id=handle.token,
            status=AsyncJobStatus.SUCCEEDED,
            pages=pages,
        )


class FakeCaptioningProvider:
    provider_version = "fake-captioning-v1"
    capabilities = dict(FAKE_VISUAL_CAPABILITY)

    def __init__(self, caption: str = "fake visual caption") -> None:
        self.caption_text = caption

    def caption(self, image: bytes, *args, **kwargs) -> CaptioningResult:
        return CaptioningResult(
            status="succeeded",
            generated_caption_text=self.caption_text,
            caption_source=CaptionSource.DETERMINISTIC_CAPTION.value,
        )


class FakeVisionProvider:
    model = "fake-vlm-v1"
    capabilities = dict(FAKE_VISUAL_CAPABILITY)

    def generate(self, query: str, *, visual_regions: Sequence[LayoutRegion]) -> str:
        for region in visual_regions:
            if region.ocr_text:
                return region.ocr_text
        return ""


def _page_from_text(text: str, *, page_number: int) -> DocumentAnalysisPage:
    bbox = BoundingBox(x=0.05, y=0.05, width=0.9, height=0.05)
    ocr = OcrTextRegion(
        text=text,
        confidence=1.0,
        bbox=bbox,
        page_number=page_number,
        extraction_source=ExtractionSource.DETERMINISTIC_OCR.value,
    )
    region = LayoutRegion(
        tenant_id="",
        collection_id="",
        document_id="",
        asset_id=f"asset_p{page_number}",
        region_id=f"asset_p{page_number}:region:1",
        bbox=bbox,
        page_number=page_number,
        region_type="text",
        heading_path=("visual",),
        ocr_text=text,
        extraction_source=ExtractionSource.DETERMINISTIC_OCR.value,
        transcription_confidence=1.0,
        metadata={"extraction_source": ExtractionSource.DETERMINISTIC_OCR.value},
    )
    return DocumentAnalysisPage(
        page_number=page_number,
        ocr_regions=(ocr,),
        layout_regions=(region,),
    )


def page_with_text(
    *,
    text: str,
    page_number: int,
    tenant_id: str = "",
    collection_id: str = "",
    document_id: str = "",
    asset_id: str | None = None,
) -> DocumentAnalysisPage:
    page = _page_from_text(text, page_number=page_number)
    final_asset_id = asset_id or f"asset_p{page_number}"
    regions = tuple(
        replace(
            region,
            tenant_id=tenant_id,
            collection_id=collection_id,
            document_id=document_id,
            asset_id=final_asset_id,
            region_id=f"{final_asset_id}:region:{idx}",
        )
        for idx, region in enumerate(page.layout_regions, start=1)
    )
    ocr = tuple(replace(region, page_number=page_number) for region in page.ocr_regions)
    return replace(page, ocr_regions=ocr, layout_regions=regions)


__all__ = [
    "FakeAsyncDocumentAnalyzer",
    "FakeCaptioningProvider",
    "FakeVisionProvider",
    "FAKE_VISUAL_CAPABILITY",
    "page_with_text",
]
