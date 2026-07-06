"""ADR-018 §7 — ``ParsedDocument``: the provider-agnostic canonical parse representation.

Phase B foundation. Per ADR §P1 the system of record is NOT ``DoclingDocument`` (nor any single
provider output, nor Markdown — §A2) but this internal contract, so that Docling, OCR providers, the
existing SpreadsheetParser, and VLM drafts can all normalize into ONE shape that carries page / block
/ table structure, citation anchors (page+bbox, spreadsheet cell), per-object provenance and quality,
and a provider ``route_trace``.

stdlib only (frozen dataclasses) — safe for the Tier A gate; heavy providers stay opt-in (§13.1) and
normalize INTO this contract elsewhere. Quality ``status`` strings are the same vocabulary as
``services.ingestion_quality`` (accepted / accepted_with_warnings / review_required / rejected /
draft_visual / manual_approved) but are held as plain ``str`` here to keep the domain layer free of a
services dependency.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, field

PARSED_DOCUMENT_SCHEMA_VERSION = "parsed_document.v1"

# --- Block kinds (ADR §7.5) ----------------------------------------------------------------------
BLOCK_TITLE = "title"
BLOCK_HEADING = "heading"
BLOCK_PARAGRAPH = "paragraph"
BLOCK_LIST_ITEM = "list_item"
BLOCK_TABLE = "table"
BLOCK_TABLE_ROW = "table_row"
BLOCK_TABLE_CELL = "table_cell"
BLOCK_FORM_FIELD = "form_field"
BLOCK_FIGURE = "figure"
BLOCK_CHART = "chart"
BLOCK_DRAWING = "drawing"
BLOCK_CAPTION = "caption"
BLOCK_HEADER = "header"
BLOCK_FOOTER = "footer"
BLOCK_HANDWRITING = "handwriting"
BLOCK_SEAL = "seal"
BLOCK_VISUAL_SUMMARY = "visual_summary"
BLOCK_UNKNOWN = "unknown"

BLOCK_KINDS = frozenset(
    {
        BLOCK_TITLE,
        BLOCK_HEADING,
        BLOCK_PARAGRAPH,
        BLOCK_LIST_ITEM,
        BLOCK_TABLE,
        BLOCK_TABLE_ROW,
        BLOCK_TABLE_CELL,
        BLOCK_FORM_FIELD,
        BLOCK_FIGURE,
        BLOCK_CHART,
        BLOCK_DRAWING,
        BLOCK_CAPTION,
        BLOCK_HEADER,
        BLOCK_FOOTER,
        BLOCK_HANDWRITING,
        BLOCK_SEAL,
        BLOCK_VISUAL_SUMMARY,
        BLOCK_UNKNOWN,
    }
)

# Source-anchor discriminants (ADR §7.4/§7.7/§10.2).
ANCHOR_PAGE_BBOX = "page_bbox"
ANCHOR_SPREADSHEET_CELL = "spreadsheet_cell"
ANCHOR_PAGE_CROP = "page_crop"

# bbox is [x0, y0, x1, y1] in the owning page's ``unit`` (default px), matching the ADR examples.
BBox = tuple[float, float, float, float]


@dataclass(frozen=True)
class SourceAnchor:
    """A citation anchor: either a page region, a spreadsheet cell, or a page crop (§7)."""

    type: str
    page_no: int | None = None
    bbox: BBox | None = None
    sheet: str | None = None
    row: int | None = None
    col: int | None = None
    header: str | None = None
    image_ref: str | None = None


@dataclass(frozen=True)
class Provenance:
    """Which provider/model produced a block/table/figure, for reproducibility & audit (§13.3)."""

    provider: str = ""
    method: str = ""
    provider_version: str = ""
    model_version: str = ""
    route: str = ""


@dataclass(frozen=True)
class QualityInfo:
    """Per-object quality: a status + reason codes + an optional dimension vector (§8.2/§8.3)."""

    status: str = "accepted"
    reasons: tuple[str, ...] = ()
    metrics: Mapping[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class Block:
    """A reading-ordered unit of content (§7.4). ``bbox``/``source_anchor`` carry the citation info."""

    block_id: str
    kind: str
    text: str = ""
    normalized_text: str = ""
    page_no: int | None = None
    bbox: BBox | None = None
    reading_order: int | None = None
    confidence: float | None = None
    source_anchor: SourceAnchor | None = None
    provenance: Provenance = field(default_factory=Provenance)
    quality: QualityInfo = field(default_factory=QualityInfo)

    @property
    def embedding_text(self) -> str:
        return self.normalized_text or self.text


@dataclass(frozen=True)
class TableColumn:
    index: int
    text: str = ""


@dataclass(frozen=True)
class TableCell:
    row: int
    col: int
    text: str = ""
    rowspan: int = 1
    colspan: int = 1
    bbox: BBox | None = None
    confidence: float | None = None
    is_header: bool = False


@dataclass(frozen=True)
class Table:
    """A structurally-preserved table (§7.6) — never flattened to a Markdown string as the record."""

    table_id: str
    page_no: int | None = None
    bbox: BBox | None = None
    columns: tuple[TableColumn, ...] = ()
    cells: tuple[TableCell, ...] = ()
    quality: QualityInfo = field(default_factory=QualityInfo)
    provenance: Provenance = field(default_factory=Provenance)


@dataclass(frozen=True)
class Figure:
    figure_id: str
    kind: str = BLOCK_FIGURE
    page_no: int | None = None
    bbox: BBox | None = None
    caption: str = ""
    image_ref: str = ""
    provenance: Provenance = field(default_factory=Provenance)
    quality: QualityInfo = field(default_factory=QualityInfo)


@dataclass(frozen=True)
class Page:
    """A page with routing signals + a page-level quality verdict (§7.3)."""

    page_id: str
    page_no: int
    width: int | None = None
    height: int | None = None
    unit: str = "px"
    page_image_ref: str = ""
    detected_languages: tuple[str, ...] = ()
    page_type: str = ""
    signals: Mapping[str, object] = field(default_factory=dict)
    quality: QualityInfo = field(default_factory=QualityInfo)


@dataclass(frozen=True)
class ProviderRun:
    """One provider execution, recorded for reproducibility / reindex / audit (§7.2/§13.3)."""

    provider: str
    provider_version: str = ""
    model_versions: Mapping[str, str] = field(default_factory=dict)
    config_hash: str = ""
    started_at: str = ""
    finished_at: str = ""
    status: str = "success"


@dataclass(frozen=True)
class RouteTraceStep:
    """One routing/extraction/fallback decision (§6.3) — for review, debug, reprocess, explanation."""

    stage: str
    provider: str = ""
    result: str = ""
    reason: str = ""
    signals: tuple[str, ...] = ()


@dataclass(frozen=True)
class SourceInfo:
    document_id: str = ""
    source_hash: str = ""
    filename: str = ""
    mime_type: str = ""
    size_bytes: int = 0


@dataclass(frozen=True)
class IngestionInfo:
    run_id: str = ""
    profile: str = "default"
    created_at: str = ""
    parser_contract_version: str = "v1"
    chunking_contract_version: str = "v1"


@dataclass(frozen=True)
class ParsedDocument:
    """The canonical, provider-agnostic parse record (ADR §7.2)."""

    schema_version: str = PARSED_DOCUMENT_SCHEMA_VERSION
    source: SourceInfo = field(default_factory=SourceInfo)
    ingestion: IngestionInfo = field(default_factory=IngestionInfo)
    provider_runs: tuple[ProviderRun, ...] = ()
    pages: tuple[Page, ...] = ()
    blocks: tuple[Block, ...] = ()
    tables: tuple[Table, ...] = ()
    figures: tuple[Figure, ...] = ()
    quality: QualityInfo = field(default_factory=QualityInfo)
    route_trace: tuple[RouteTraceStep, ...] = ()

    def ordered_blocks(self) -> tuple[Block, ...]:
        """Blocks in reading order (``reading_order`` when set, else document order — stable sort)."""

        def sort_key(pair: tuple[int, Block]) -> tuple[float, int]:
            idx, block = pair
            order = block.reading_order if block.reading_order is not None else idx
            return (order, idx)

        return tuple(block for _idx, block in sorted(enumerate(self.blocks), key=sort_key))

    def text_for_embedding(self) -> str:
        """Reading-ordered plain text derived from blocks (§P2: Markdown/text are DERIVED, not record)."""

        return "\n\n".join(
            block.embedding_text for block in self.ordered_blocks() if block.embedding_text.strip()
        )

    def to_dict(self) -> dict:
        """Lossless dict for raw persistence / serialization (tuples become lists)."""

        return asdict(self)
