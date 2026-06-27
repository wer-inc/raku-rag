"""Provider-neutral visual understanding interfaces.

These protocols keep deterministic local providers and real production adapters behind the same
contracts. PDF/multi-page document analysis is intentionally asynchronous; single images can still use
the synchronous OCR/layout path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, Sequence

from raku_rag.domain.models import LayoutRegion, OcrTextRegion


@dataclass(frozen=True)
class IngestContext:
    tenant_id: str
    collection_id: str
    source_id: str
    document_id: str
    content_type: str = "image/png"
    job_id: str = ""
    trace_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class AsyncJobStatus(str, Enum):
    PENDING = "PENDING"
    MORE_AVAILABLE = "MORE_AVAILABLE"
    PARTIAL_FAILURE = "PARTIAL_FAILURE"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class AsyncSubmitRequest:
    document_ref: str
    context: IngestContext
    feature_types: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class JobHandle:
    provider: str
    token: str
    document_ref: str
    status: AsyncJobStatus = AsyncJobStatus.PENDING
    continuation: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DocumentAnalysisPage:
    page_number: int
    ocr_regions: tuple[OcrTextRegion, ...] = ()
    layout_regions: tuple[LayoutRegion, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DocumentAnalysis:
    provider: str
    job_id: str
    status: AsyncJobStatus
    pages: tuple[DocumentAnalysisPage, ...] = ()
    failure_reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class OcrEngine(Protocol):
    def extract(self, image: bytes, *args: Any, **kwargs: Any) -> tuple[OcrTextRegion, ...]: ...


class LayoutExtractor(Protocol):
    def extract(self, image: bytes, *args: Any, **kwargs: Any) -> tuple[LayoutRegion, ...]: ...


class StructuredExtractor(Protocol):
    def extract(self, regions: Sequence[LayoutRegion], *args: Any, **kwargs: Any) -> object: ...


class CaptioningProvider(Protocol):
    def caption(self, image: bytes, *args: Any, **kwargs: Any) -> object: ...


class VLMProvider(Protocol):
    def generate(self, query: str, *, visual_regions: Sequence[LayoutRegion]) -> str: ...


class AsyncDocumentAnalyzer(Protocol):
    def submit(self, request: AsyncSubmitRequest) -> JobHandle: ...

    def poll(self, handle: JobHandle) -> DocumentAnalysis: ...


__all__ = [
    "AsyncDocumentAnalyzer",
    "AsyncJobStatus",
    "AsyncSubmitRequest",
    "CaptioningProvider",
    "DocumentAnalysis",
    "DocumentAnalysisPage",
    "IngestContext",
    "JobHandle",
    "LayoutExtractor",
    "OcrEngine",
    "StructuredExtractor",
    "VLMProvider",
]
