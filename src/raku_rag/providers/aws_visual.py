"""AWS visual-understanding providers.

The module is import-safe without boto3. Real AWS clients are created lazily by invokers, while tests
inject tiny fake clients to validate request/response handling offline.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Mapping, Sequence
from typing import Any, Callable
from urllib.parse import urlparse

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

TextractInvoker = Callable[[bytes], Mapping[str, object]]
BedrockVisionInvoker = Callable[..., str]

_DEFAULT_REGION = "ap-northeast-1"
_DEFAULT_CLAUDE_VISION_MODEL_ID = "jp.anthropic.claude-sonnet-4-5-20250929-v1:0"


def build_textract_analyze_invoker(
    *,
    region_name: str = _DEFAULT_REGION,
    client: object | None = None,
    feature_types: Sequence[str] = ("TABLES", "FORMS"),
) -> TextractInvoker:
    state: dict[str, object | None] = {"client": client}

    def _invoke(image: bytes) -> Mapping[str, object]:
        if state["client"] is None:
            import boto3  # type: ignore

            state["client"] = boto3.client("textract", region_name=region_name)
        return state["client"].analyze_document(  # type: ignore[attr-defined]
            Document={"Bytes": image},
            FeatureTypes=list(feature_types),
        )

    return _invoke


def build_bedrock_vision_invoker(
    *,
    region_name: str = _DEFAULT_REGION,
    client: object | None = None,
) -> BedrockVisionInvoker:
    state: dict[str, object | None] = {"client": client}

    def _invoke(
        *,
        model_id: str,
        prompt: str,
        max_tokens: int = 512,
        image: bytes | None = None,
        media_type: str = "image/png",
    ) -> str:
        if state["client"] is None:
            import boto3  # type: ignore

            state["client"] = boto3.client("bedrock-runtime", region_name=region_name)
        content: list[dict[str, object] | str] = []
        if image:
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": base64.b64encode(image).decode("ascii"),
                    },
                }
            )
        content.append({"type": "text", "text": prompt})
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": content}],
        }
        response = state["client"].invoke_model(  # type: ignore[attr-defined]
            modelId=model_id,
            body=json.dumps(body).encode("utf-8"),
            accept="application/json",
            contentType="application/json",
        )
        payload = json.loads(response["body"].read().decode("utf-8"))
        blocks = payload.get("content") or []
        return "".join(
            block.get("text", "")
            for block in blocks
            if isinstance(block, Mapping) and block.get("type") == "text"
        )

    return _invoke


class TextractOcrEngine:
    provider_id = "aws_textract"
    provider_family = "aws"
    engine_version = "aws-textract-ocr-v1"
    zero_retention = True
    no_train = True

    def __init__(
        self,
        *,
        region: str = _DEFAULT_REGION,
        invoker: TextractInvoker | None = None,
    ) -> None:
        self.region = region
        self._invoker = invoker or build_textract_analyze_invoker(region_name=region)

    def extract(self, image: bytes, *args: Any, **kwargs: Any) -> tuple[OcrTextRegion, ...]:
        return textract_ocr_regions(self._invoker(image))


class TextractLayoutExtractor:
    provider_id = "aws_textract"
    provider_family = "aws"
    extractor_version = "aws-textract-layout-v1"
    zero_retention = True
    no_train = True

    def __init__(
        self,
        *,
        region: str = _DEFAULT_REGION,
        invoker: TextractInvoker | None = None,
    ) -> None:
        self.region = region
        self._invoker = invoker or build_textract_analyze_invoker(region_name=region)

    def extract(
        self,
        image: bytes,
        *,
        tenant_id: str = "",
        collection_id: str = "",
        document_id: str = "",
        asset_id: str = "",
        ocr_regions: Sequence[OcrTextRegion] | None = None,
        **kwargs: Any,
    ) -> tuple[LayoutRegion, ...]:
        if ocr_regions is not None:
            return layout_regions_from_ocr(
                ocr_regions,
                tenant_id=tenant_id,
                collection_id=collection_id,
                document_id=document_id,
                asset_id=asset_id,
                extractor_version=self.extractor_version,
            )
        return textract_layout_regions(
            self._invoker(image),
            tenant_id=tenant_id,
            collection_id=collection_id,
            document_id=document_id,
            asset_id=asset_id,
            extractor_version=self.extractor_version,
        )


class TextractStructuredExtractor:
    provider_id = "aws_textract"
    provider_family = "aws"
    extractor_version = "aws-textract-structured-v1"
    zero_retention = True
    no_train = True

    def __init__(self, *, region: str = _DEFAULT_REGION) -> None:
        self.region = region

    def extract(self, regions: Sequence[LayoutRegion], *args: Any, **kwargs: Any) -> tuple[dict, ...]:
        structured: list[dict] = []
        for region in regions:
            if region.region_type in {"table", "form_field"} or region.metadata.get(
                "structured_content"
            ):
                structured.append(
                    {
                        "region_id": region.region_id,
                        "region_type": region.region_type,
                        "text": region.ocr_text,
                        "metadata": dict(region.metadata),
                    }
                )
        return tuple(structured)


class TextractAsyncDocumentAnalyzer:
    provider_id = "aws_textract"
    provider_family = "aws"
    extractor_version = "aws-textract-async-v1"
    zero_retention = True
    no_train = True

    def __init__(
        self,
        *,
        region: str = _DEFAULT_REGION,
        client: object | None = None,
        feature_types: Sequence[str] = ("TABLES", "FORMS"),
    ) -> None:
        self.region = region
        self.feature_types = tuple(feature_types)
        self._client = client

    def _textract(self) -> object:
        if self._client is None:
            import boto3  # type: ignore

            self._client = boto3.client("textract", region_name=self.region)
        return self._client

    def submit(self, request: AsyncSubmitRequest) -> JobHandle:
        bucket, key = _parse_s3_ref(request.document_ref)
        response = self._textract().start_document_analysis(  # type: ignore[attr-defined]
            DocumentLocation={"S3Object": {"Bucket": bucket, "Name": key}},
            FeatureTypes=list(request.feature_types or self.feature_types),
        )
        job_id = str(response.get("JobId") or "")
        return JobHandle(
            provider=self.provider_id,
            token=job_id,
            document_ref=request.document_ref,
            status=AsyncJobStatus.PENDING,
        )

    def poll(self, handle: JobHandle) -> DocumentAnalysis:
        response = self._textract().get_document_analysis(JobId=handle.token)  # type: ignore[attr-defined]
        status = str(response.get("JobStatus") or "")
        if status in {"IN_PROGRESS", "SUCCEEDED_WITH_WARNINGS"}:
            return DocumentAnalysis(
                provider=self.provider_id,
                job_id=handle.token,
                status=AsyncJobStatus.PENDING,
                metadata={"extractor_version": self.extractor_version},
            )
        if status == "FAILED":
            return DocumentAnalysis(
                provider=self.provider_id,
                job_id=handle.token,
                status=AsyncJobStatus.FAILED,
                failure_reason=str(response.get("StatusMessage") or "textract analysis failed"),
                metadata={"extractor_version": self.extractor_version},
            )
        pages = document_pages_from_textract(
            response,
            extractor_version=self.extractor_version,
        )
        return DocumentAnalysis(
            provider=self.provider_id,
            job_id=handle.token,
            status=AsyncJobStatus.SUCCEEDED,
            pages=pages,
            metadata={"extractor_version": self.extractor_version},
        )


class BedrockVisionCaptioningProvider:
    provider_id = "bedrock"
    provider_family = "aws"
    provider_version = "bedrock-vision-caption-v1"
    zero_retention = True
    no_train = True

    def __init__(
        self,
        *,
        model_id: str = _DEFAULT_CLAUDE_VISION_MODEL_ID,
        region: str = _DEFAULT_REGION,
        invoker: BedrockVisionInvoker | None = None,
        max_tokens: int = 256,
    ) -> None:
        self.model = model_id or _DEFAULT_CLAUDE_VISION_MODEL_ID
        self.region = region
        self._invoker = invoker or build_bedrock_vision_invoker(region_name=region)
        self._max_tokens = max_tokens

    def caption(self, image: bytes, *args: Any, **kwargs: Any) -> CaptioningResult:
        media_type = str(kwargs.get("content_type") or kwargs.get("media_type") or "image/png")
        prompt = (
            "Describe the image in concise factual language. Do not infer hidden state. "
            "If text is visible, transcribe it exactly."
        )
        text = self._invoker(
            model_id=self.model,
            prompt=prompt,
            max_tokens=self._max_tokens,
            image=image,
            media_type=media_type,
        )
        return CaptioningResult(
            status="succeeded" if text else "failed",
            generated_caption_text=text,
            caption_source=CaptionSource.BEDROCK_CLAUDE_VISION.value if text else "",
            failure_reason="" if text else "empty bedrock caption response",
        )


class BedrockVisionVLMProvider:
    provider_id = "bedrock"
    provider_family = "aws"
    zero_retention = True
    no_train = True

    def __init__(
        self,
        *,
        model_id: str = _DEFAULT_CLAUDE_VISION_MODEL_ID,
        region: str = _DEFAULT_REGION,
        invoker: BedrockVisionInvoker | None = None,
        max_tokens: int = 768,
    ) -> None:
        self.model = model_id or _DEFAULT_CLAUDE_VISION_MODEL_ID
        self.region = region
        self._invoker = invoker or build_bedrock_vision_invoker(region_name=region)
        self._max_tokens = max_tokens

    def generate(self, query: str, *, visual_regions: Sequence[LayoutRegion]) -> str:
        evidence = "\n".join(
            f"- page={region.page_number} region={region.region_id}: {region.ocr_text}"
            for region in visual_regions
            if region.ocr_text
        )
        if not evidence:
            return ""
        prompt = (
            "Answer using only the visual OCR evidence below. If the evidence is insufficient, "
            "say that the evidence is insufficient.\n\n"
            f"Question: {query}\n\nEvidence:\n{evidence}"
        )
        return self._invoker(model_id=self.model, prompt=prompt, max_tokens=self._max_tokens)


def textract_ocr_regions(response: Mapping[str, object]) -> tuple[OcrTextRegion, ...]:
    regions: list[OcrTextRegion] = []
    for block in _blocks(response):
        if str(block.get("BlockType") or "") != "LINE":
            continue
        text = str(block.get("Text") or "").strip()
        if not text:
            continue
        regions.append(
            OcrTextRegion(
                text=text,
                confidence=_confidence(block),
                bbox=_bbox(block),
                page_number=_page(block),
                extraction_source=ExtractionSource.AWS_TEXTRACT.value,
            )
        )
    return tuple(regions)


def textract_layout_regions(
    response: Mapping[str, object],
    *,
    tenant_id: str,
    collection_id: str,
    document_id: str,
    asset_id: str,
    extractor_version: str,
) -> tuple[LayoutRegion, ...]:
    return layout_regions_from_ocr(
        textract_ocr_regions(response),
        tenant_id=tenant_id,
        collection_id=collection_id,
        document_id=document_id,
        asset_id=asset_id,
        extractor_version=extractor_version,
    )


def layout_regions_from_ocr(
    ocr_regions: Sequence[OcrTextRegion],
    *,
    tenant_id: str,
    collection_id: str,
    document_id: str,
    asset_id: str,
    extractor_version: str,
) -> tuple[LayoutRegion, ...]:
    effective_asset_id = asset_id or "asset_textract"
    return tuple(
        LayoutRegion(
            tenant_id=tenant_id,
            collection_id=collection_id,
            document_id=document_id,
            asset_id=effective_asset_id,
            region_id=f"{effective_asset_id}:p{ocr.page_number}:region:{idx}",
            bbox=ocr.bbox,
            page_number=ocr.page_number,
            region_type="text",
            heading_path=("visual",),
            ocr_text=ocr.text,
            extraction_source=ocr.extraction_source or ExtractionSource.AWS_TEXTRACT.value,
            transcription_confidence=ocr.confidence,
            metadata={"extractor_version": extractor_version},
        )
        for idx, ocr in enumerate(ocr_regions, start=1)
    )


def document_pages_from_textract(
    response: Mapping[str, object],
    *,
    extractor_version: str,
) -> tuple[DocumentAnalysisPage, ...]:
    ocr_regions = textract_ocr_regions(response)
    pages = sorted({region.page_number for region in ocr_regions}) or [1]
    return tuple(
        DocumentAnalysisPage(
            page_number=page,
            ocr_regions=tuple(region for region in ocr_regions if region.page_number == page),
            layout_regions=layout_regions_from_ocr(
                tuple(region for region in ocr_regions if region.page_number == page),
                tenant_id="",
                collection_id="",
                document_id="",
                asset_id=f"asset_p{page}",
                extractor_version=extractor_version,
            ),
            metadata={"extractor_version": extractor_version},
        )
        for page in pages
    )


def _blocks(response: Mapping[str, object]) -> tuple[Mapping[str, object], ...]:
    raw = response.get("Blocks") or ()
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return ()
    return tuple(block for block in raw if isinstance(block, Mapping))


def _bbox(block: Mapping[str, object]) -> BoundingBox:
    geometry = block.get("Geometry") if isinstance(block.get("Geometry"), Mapping) else {}
    raw = geometry.get("BoundingBox") if isinstance(geometry, Mapping) else {}
    bbox = raw if isinstance(raw, Mapping) else {}
    return BoundingBox(
        x=_float(bbox.get("Left")),
        y=_float(bbox.get("Top")),
        width=_float(bbox.get("Width"), default=1.0),
        height=_float(bbox.get("Height"), default=0.05),
    )


def _confidence(block: Mapping[str, object]) -> float:
    return max(0.0, min(_float(block.get("Confidence"), default=100.0) / 100.0, 1.0))


def _page(block: Mapping[str, object]) -> int:
    try:
        return int(block.get("Page") or 1)
    except (TypeError, ValueError):
        return 1


def _float(value: object, *, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_s3_ref(document_ref: str) -> tuple[str, str]:
    parsed = urlparse(document_ref)
    if parsed.scheme != "s3" or not parsed.netloc or not parsed.path.strip("/"):
        raise ValueError("Textract async document analysis requires an s3://bucket/key ref")
    return parsed.netloc, parsed.path.lstrip("/")


__all__ = [
    "BedrockVisionCaptioningProvider",
    "BedrockVisionVLMProvider",
    "TextractAsyncDocumentAnalyzer",
    "TextractLayoutExtractor",
    "TextractOcrEngine",
    "TextractStructuredExtractor",
    "build_bedrock_vision_invoker",
    "build_textract_analyze_invoker",
    "document_pages_from_textract",
    "layout_regions_from_ocr",
    "textract_layout_regions",
    "textract_ocr_regions",
]
