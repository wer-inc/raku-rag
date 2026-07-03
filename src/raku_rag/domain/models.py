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


class ExtractionSource(str, Enum):
    DETERMINISTIC_OCR = "deterministic_ocr"
    AWS_TEXTRACT = "aws_textract"
    GOOGLE_DOCAI = "google_docai"
    AZURE_DOCINTEL = "azure_docintel"
    OSS_TESSERACT = "oss_tesseract"
    SPREADSHEET_PARSER = "spreadsheet_parser"


class CaptionSource(str, Enum):
    DETERMINISTIC_CAPTION = "deterministic_caption"
    BEDROCK_CLAUDE_VISION = "bedrock_claude_vision"
    GOOGLE_GEMINI = "google_gemini"
    AZURE_OPENAI_VISION = "azure_openai_vision"
    OSS_LLAVA = "oss_llava"


PROMOTABLE_EXTRACTION_SOURCES = frozenset(source.value for source in ExtractionSource)


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


# ★G5: the QueryProfile.llm_model default. Profiles carrying this value (or "") have expressed NO
# explicit model preference — AnswerService then uses its wired default provider without treating
# it as a routing fallback. Only an explicitly-set, different model name participates in routing.
DEFAULT_LLM_MODEL = "extractive-mvp"


@dataclass(frozen=True)
class QueryProfile:
    """Search/answer behaviour, configurable per collection/query (FR-014a)."""

    profile_id: str = "default"
    score_threshold: float = 0.10
    top_k: int = 5
    minimum_evidence_count: int = 1
    rerank_enabled: bool = True
    rerank_top_n: int = 20
    query_rewrite_enabled: bool = False
    max_context_tokens: int = 8_000
    max_context_chunks: int = 8
    max_synchronous_llm_calls: int = 1
    self_eval_enabled: bool = True
    # ★G5 model routing knob (tenant-tunable via the admin retrieval-profiles/query-profiles API):
    # when AnswerService is constructed with an ``llm_by_model`` registry and this names one of its
    # keys, generation uses that provider; unknown names fall back to the default (fail-open,
    # logged). The dataclass default means "no preference" (see DEFAULT_LLM_MODEL).
    llm_model: str = DEFAULT_LLM_MODEL
    # ★G2 no-answer gate knob: minimum fraction of the question's content-terms that the USED
    # evidence must contain, else the answer is refused as insufficient_evidence. OFF by default
    # (0.0): measured coverage does NOT separate relevant from irrelevant for short Japanese
    # queries (legit "その圧力の抜き方" vs its correct doc scores 0.17 — below irrelevant English
    # cases) because particles/inflection dilute the CJK-bigram terms. Tenant-tunable opt-in via
    # the retrieval profiles API for corpora where query/document vocabulary is aligned.
    min_question_coverage: float = 0.0


@dataclass(frozen=True)
class ScoredChunk:
    chunk: Chunk
    retrieval_score: float


@dataclass(frozen=True)
class Citation:
    """Traceable evidence actually cited (FR-013/015)."""

    kind: str  # text | visual | spreadsheet | table_row | form_field | chart_series | etc.
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
    sheet_name: str = ""
    cell_range: str = ""
    row_id: str = ""
    table_id: str = ""
    form_id: str = ""
    field_name: str = ""
    chart_id: str = ""
    series_name: str = ""
    point_index: int = -1
    column_name: str = ""
    pixel_derived: bool = False
    visual_evidence_verified: bool = False
    visual_verifier_verdicts: tuple[dict, ...] = ()
    metadata: dict = field(default_factory=dict)


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
    extraction_source: str = ""


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
    extraction_source: str = ""
    caption_source: str = ""
    transcription_confidence: float | None = None
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
    route: str = "rag"
