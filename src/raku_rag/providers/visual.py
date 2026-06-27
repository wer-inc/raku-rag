"""Visual provider selection.

Real visual providers are selected only by explicit settings. The deterministic stack remains the
default even when ``runtime_profile`` is ``production`` so enabling Bedrock/Textract is a deliberate
tenant/runtime decision rather than an accidental profile side effect.
"""

from __future__ import annotations

from typing import Callable, Sequence

from raku_rag.core.config import Settings
from raku_rag.domain.models import LayoutRegion, OcrTextRegion
from raku_rag.interfaces.base import Vector
from raku_rag.providers.captioning import CaptioningResult, DeterministicCaptioningProvider
from raku_rag.providers.layout import DeterministicLayoutExtractor
from raku_rag.providers.ocr import DeterministicOcrEngine
from raku_rag.providers.visual_embeddings import HashingVisualEmbeddingProvider
from raku_rag.providers.vlms import ExtractiveVLMProvider

OcrInvoker = Callable[..., tuple[OcrTextRegion, ...]]
LayoutInvoker = Callable[..., tuple[LayoutRegion, ...]]
StructuredInvoker = Callable[..., object]
CaptioningInvoker = Callable[..., CaptioningResult]
VlmInvoker = Callable[[str, Sequence[LayoutRegion]], str]
VisualEmbeddingInvoker = Callable[[Sequence[bytes]], list[Vector]]


def _normalize(value: str) -> str:
    return value.strip().lower().replace("-", "_")


def _runtime_profile(settings: Settings) -> str:
    profile = _normalize(settings.runtime_profile)
    if profile not in {"deterministic", "production"}:
        raise ValueError(f"unknown runtime_profile: {settings.runtime_profile}")
    return profile


def _selected_visual_provider(settings: Settings, raw_provider: str) -> str:
    profile = _runtime_profile(settings)
    provider = _normalize(raw_provider or "deterministic")
    if getattr(settings, "force_deterministic", False) or profile == "deterministic":
        return "deterministic"
    if provider in {"", "deterministic"}:
        return "deterministic"
    return provider


def _textract_region(settings: Settings) -> str:
    return str(settings.ocr_region or settings.textract_region or settings.aws_region)


def _vlm_region(settings: Settings) -> str:
    return str(settings.vlm_region or settings.aws_region)


class DeterministicStructuredExtractor:
    extractor_version = "deterministic-structured-v1"

    def extract(self, regions: Sequence[LayoutRegion], *args, **kwargs) -> tuple[object, ...]:
        return ()


class InvokerOcrEngine:
    engine_version = "external-ocr-v1"

    def __init__(self, *, provider_id: str, invoker: OcrInvoker | None = None) -> None:
        self.provider_id = provider_id
        self._invoker = invoker

    def extract(self, image: bytes, *args, **kwargs) -> tuple[OcrTextRegion, ...]:
        if self._invoker is None:
            raise RuntimeError(f"{self.provider_id}_ocr_not_configured")
        return tuple(self._invoker(image, *args, **kwargs))


class InvokerLayoutExtractor:
    extractor_version = "external-layout-v1"

    def __init__(self, *, provider_id: str, invoker: LayoutInvoker | None = None) -> None:
        self.provider_id = provider_id
        self._invoker = invoker

    def extract(self, image: bytes, *args, **kwargs) -> tuple[LayoutRegion, ...]:
        if self._invoker is None:
            raise RuntimeError(f"{self.provider_id}_layout_not_configured")
        return tuple(self._invoker(image, *args, **kwargs))


class InvokerStructuredExtractor:
    extractor_version = "external-structured-v1"

    def __init__(self, *, provider_id: str, invoker: StructuredInvoker | None = None) -> None:
        self.provider_id = provider_id
        self._invoker = invoker

    def extract(self, regions: Sequence[LayoutRegion], *args, **kwargs) -> object:
        if self._invoker is None:
            raise RuntimeError(f"{self.provider_id}_structured_not_configured")
        return self._invoker(regions, *args, **kwargs)


class InvokerCaptioningProvider:
    provider_version = "external-captioning-v1"

    def __init__(self, *, provider_id: str, invoker: CaptioningInvoker | None = None) -> None:
        self.provider_id = provider_id
        self._invoker = invoker

    def caption(self, image: bytes, *args, **kwargs) -> CaptioningResult:
        if self._invoker is None:
            raise RuntimeError(f"{self.provider_id}_captioning_not_configured")
        return self._invoker(image, *args, **kwargs)


class InvokerVLMProvider:
    model = "external-vlm-v1"

    def __init__(self, *, provider_id: str, invoker: VlmInvoker | None = None) -> None:
        self.provider_id = provider_id
        self._invoker = invoker
        self.model = provider_id

    def generate(self, query: str, *, visual_regions: Sequence[LayoutRegion]) -> str:
        if self._invoker is None:
            raise RuntimeError(f"{self.provider_id}_vlm_not_configured")
        return self._invoker(query, visual_regions)


class InvokerVisualEmbeddingProvider:
    model_version = "external-visual-embedding-v1"

    def __init__(
        self, *, provider_id: str, invoker: VisualEmbeddingInvoker | None = None
    ) -> None:
        self.provider_id = provider_id
        self._invoker = invoker
        self.model_version = provider_id

    def embed(self, regions: Sequence[bytes]) -> list[Vector]:
        if self._invoker is None:
            raise RuntimeError(f"{self.provider_id}_visual_embedding_not_configured")
        return list(self._invoker(regions))


def ocr_from_settings(
    settings: Settings, *, invoker: OcrInvoker | None = None
) -> object:
    provider = _selected_visual_provider(settings, settings.ocr_provider)
    if provider == "deterministic":
        return DeterministicOcrEngine()
    if provider == "aws_textract":
        if invoker is not None:
            return InvokerOcrEngine(provider_id=provider, invoker=invoker)
        from raku_rag.providers.aws_visual import TextractOcrEngine

        return TextractOcrEngine(region=_textract_region(settings))
    raise ValueError(f"unknown ocr_provider: {settings.ocr_provider}")


def async_document_analyzer_from_settings(settings: Settings) -> object | None:
    provider = _selected_visual_provider(settings, settings.ocr_provider)
    if provider == "aws_textract":
        from raku_rag.providers.aws_visual import TextractAsyncDocumentAnalyzer

        return TextractAsyncDocumentAnalyzer(region=_textract_region(settings))
    if provider == "deterministic":
        return None
    raise ValueError(f"unknown async visual document provider: {settings.ocr_provider}")


def layout_from_settings(
    settings: Settings, *, invoker: LayoutInvoker | None = None
) -> object:
    provider = _selected_visual_provider(settings, settings.layout_provider)
    if provider == "deterministic":
        return DeterministicLayoutExtractor()
    if provider == "aws_textract":
        if invoker is not None:
            return InvokerLayoutExtractor(provider_id=provider, invoker=invoker)
        from raku_rag.providers.aws_visual import TextractLayoutExtractor

        return TextractLayoutExtractor(region=_textract_region(settings))
    if provider in {"google_docai", "google_document_ai", "azure_docintel"}:
        return InvokerLayoutExtractor(provider_id=provider, invoker=invoker)
    raise ValueError(f"unknown layout_provider: {settings.layout_provider}")


def structured_from_settings(
    settings: Settings, *, invoker: StructuredInvoker | None = None
) -> object:
    provider = _selected_visual_provider(settings, settings.structured_provider)
    if provider == "deterministic":
        return DeterministicStructuredExtractor()
    if provider == "aws_textract":
        if invoker is not None:
            return InvokerStructuredExtractor(provider_id=provider, invoker=invoker)
        from raku_rag.providers.aws_visual import TextractStructuredExtractor

        return TextractStructuredExtractor(region=_textract_region(settings))
    if provider in {
        "google_docai",
        "google_document_ai",
        "azure_docintel",
        "azure_document_intelligence",
    }:
        return InvokerStructuredExtractor(provider_id=provider, invoker=invoker)
    raise ValueError(f"unknown structured_provider: {settings.structured_provider}")


def captioning_from_settings(
    settings: Settings, *, invoker: CaptioningInvoker | None = None
) -> object:
    provider = _selected_visual_provider(settings, settings.captioning_provider)
    if provider == "deterministic":
        return DeterministicCaptioningProvider()
    if provider == "bedrock":
        if invoker is not None:
            return InvokerCaptioningProvider(provider_id=provider, invoker=invoker)
        from raku_rag.providers.aws_visual import BedrockVisionCaptioningProvider

        return BedrockVisionCaptioningProvider(
            model_id=settings.caption_model_id or settings.vlm_model_id,
            region=_vlm_region(settings),
        )
    if provider in {"google_gemini", "vertex_gemini", "oss_llava"}:
        return InvokerCaptioningProvider(provider_id=provider, invoker=invoker)
    raise ValueError(f"unknown captioning_provider: {settings.captioning_provider}")


def vlm_from_settings(
    settings: Settings, *, invoker: VlmInvoker | None = None
) -> object:
    provider = _selected_visual_provider(settings, settings.vlm_provider)
    if provider == "deterministic":
        return ExtractiveVLMProvider()
    if provider == "bedrock":
        if invoker is not None:
            return InvokerVLMProvider(provider_id=provider, invoker=invoker)
        from raku_rag.providers.aws_visual import BedrockVisionVLMProvider

        return BedrockVisionVLMProvider(
            model_id=settings.vlm_model_id or settings.caption_model_id,
            region=_vlm_region(settings),
        )
    if provider in {"google_gemini", "vertex_gemini", "oss_llava"}:
        return InvokerVLMProvider(provider_id=provider, invoker=invoker)
    raise ValueError(f"unknown vlm_provider: {settings.vlm_provider}")


def visual_embedding_from_settings(
    settings: Settings, *, invoker: VisualEmbeddingInvoker | None = None
) -> HashingVisualEmbeddingProvider | InvokerVisualEmbeddingProvider:
    provider = _selected_visual_provider(settings, settings.visual_embedding_provider)
    if provider == "deterministic":
        return HashingVisualEmbeddingProvider(dim=settings.embedding_dim)
    if provider in {"titan_multimodal", "bedrock_titan_multimodal", "vertex_embeddings"}:
        provider_id = "bedrock" if provider in {"titan_multimodal", "bedrock_titan_multimodal"} else provider
        return InvokerVisualEmbeddingProvider(provider_id=provider_id, invoker=invoker)
    raise ValueError(f"unknown visual_embedding_provider: {settings.visual_embedding_provider}")


__all__ = [
    "CaptioningInvoker",
    "DeterministicStructuredExtractor",
    "InvokerCaptioningProvider",
    "InvokerLayoutExtractor",
    "InvokerOcrEngine",
    "InvokerStructuredExtractor",
    "InvokerVLMProvider",
    "InvokerVisualEmbeddingProvider",
    "LayoutInvoker",
    "OcrInvoker",
    "StructuredInvoker",
    "VlmInvoker",
    "VisualEmbeddingInvoker",
    "async_document_analyzer_from_settings",
    "captioning_from_settings",
    "layout_from_settings",
    "ocr_from_settings",
    "structured_from_settings",
    "vlm_from_settings",
    "visual_embedding_from_settings",
]
