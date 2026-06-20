"""T007 — domain entities (Pydantic in production; stdlib dataclasses for the MVP core).

Every persisted entity carries ``tenant_id`` (FR-021). Chunks carry ``modality`` and inherit
the document ACL. Visual entities (VisualAsset/LayoutRegion/Crop) are defined in US6 (out of MVP
scope) and intentionally omitted here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Modality(str, Enum):
    TEXT = "text"
    VISUAL = "visual"  # populated in US6


class ScopeType(str, Enum):
    TENANT = "tenant"
    COLLECTION = "collection"
    DOCUMENT = "document"


class SubjectType(str, Enum):
    USER = "user"
    GROUP = "group"
    ROLE = "role"


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DEAD_LETTER = "dead_letter"


@dataclass(frozen=True)
class IdentityClaims:
    """Verified end-user claims asserted by the calling app via signed token (FR-025)."""

    tenant_id: str
    user_id: str
    groups: tuple[str, ...] = ()
    roles: tuple[str, ...] = ()


@dataclass(frozen=True)
class ACLGrant:
    """deny-by-default permission record (FR-022/025a)."""

    tenant_id: str
    scope_type: ScopeType
    scope_id: str
    subject_type: SubjectType
    subject_id: str
    permission: str = "read"


@dataclass
class Document:
    tenant_id: str
    collection_id: str
    document_id: str
    source_id: str
    version: int = 1
    checksum: str = ""
    metadata: dict = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""
    indexed_at: str = ""
    tombstone: bool = False  # required retrieval filter (FR-008)


@dataclass
class Chunk:
    tenant_id: str
    chunk_id: str
    document_id: str
    collection_id: str
    text: str
    position: int = 0
    token_count: int = 0
    heading_path: tuple[str, ...] = ()
    modality: Modality = Modality.TEXT
    embedding_model_version: str = ""
    offset_mapping: tuple[tuple[int, int], int] | None = None  # (orig start,end)->normalized
    metadata: dict = field(default_factory=dict)
    tombstone: bool = False  # propagated from document


@dataclass(frozen=True)
class QueryProfile:
    """Search/answer behaviour, configurable per collection/query (FR-014a)."""

    profile_id: str = "default"
    score_threshold: float = 0.10
    top_k: int = 5
    minimum_evidence_count: int = 1
    rerank_enabled: bool = True
    rerank_top_n: int = 50
    query_rewrite_enabled: bool = False
    self_eval_enabled: bool = True
    llm_model: str = "extractive-mvp"


@dataclass(frozen=True)
class ScoredChunk:
    chunk: Chunk
    retrieval_score: float


@dataclass(frozen=True)
class Citation:
    """Traceable evidence actually cited (FR-013/015). kind=text or visual."""

    kind: str  # "text" | "visual"
    document_id: str
    source_id: str
    version: int
    retrieval_score: float
    chunk_id: str | None = None
    text_range: tuple[int, int] | None = None  # code-point offsets on normalized text
    asset_id: str = ""
    page_number: int = 0
    region_id: str = ""
    bbox: BoundingBox | None = None
    crop_uri: str = ""


@dataclass(frozen=True)
class Freshness:
    indexed_at: str
    document_version: int
    source_freshness: str = ""


@dataclass(frozen=True)
class BoundingBox:
    """Normalized visual coordinates: x/y/width/height in the 0..1 page coordinate space."""

    x: float
    y: float
    width: float
    height: float


@dataclass(frozen=True)
class OcrTextRegion:
    text: str
    confidence: float
    bbox: BoundingBox
    page_number: int = 1


@dataclass
class VisualAsset:
    tenant_id: str
    collection_id: str
    document_id: str
    asset_id: str
    storage_uri: str
    checksum: str
    content_type: str = "image/png"
    version: int = 1
    page_number: int = 1
    metadata: dict = field(default_factory=dict)
    tombstone: bool = False


@dataclass
class LayoutRegion:
    tenant_id: str
    collection_id: str
    document_id: str
    asset_id: str
    region_id: str
    bbox: BoundingBox
    page_number: int = 1
    region_type: str = "text"
    heading_path: tuple[str, ...] = ()
    ocr_text: str = ""
    generated_caption_text: str = ""
    crop_uri: str = ""
    metadata: dict = field(default_factory=dict)
    tombstone: bool = False


@dataclass(frozen=True)
class VisualCitation:
    asset_id: str
    document_id: str
    page_number: int
    bbox: BoundingBox
    retrieval_score: float
    region_id: str = ""
    crop_uri: str = ""
    ocr_text: str = ""


@dataclass
class CropArtifact:
    tenant_id: str
    collection_id: str
    document_id: str
    asset_id: str
    region_id: str
    crop_id: str
    bbox: BoundingBox
    crop_uri: str
    redaction_policy_ref: str = "inherit"
    metadata: dict = field(default_factory=dict)
    tombstone: bool = False


@dataclass(frozen=True)
class Answer:
    status: str  # AnswerStatus value
    text: str | None = None
    confidence: float | None = None
    citations: tuple[Citation, ...] = ()
    used_chunks: tuple[str, ...] = ()
    used_modalities: tuple[str, ...] = ()
    freshness: tuple[Freshness, ...] = ()
    cost: dict = field(default_factory=dict)
    correlation_id: str = ""
