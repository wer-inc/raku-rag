"""ADR-018 §9.1 — DoclingStructuredParser: Docling as the first-choice structured provider (Phase B4).

Docling is an OPT-IN heavy provider (§13.1): torch + layout/table models. This adapter imports it
lazily, so the Tier A gate and the default runtime never pull it in. When Docling is unavailable the
parser degrades to a deterministic offline fallback (text decode + a route_trace note) rather than
crashing — the same "heavy provider is optional in core, verified out-of-gate" pattern the project
uses for Bedrock / Textract / VLM.

Crucially (§P1) the output is normalized into our canonical ``ParsedDocument``; the raw
``DoclingDocument`` is provider output kept for reproducibility (§P2), never the record.
"""

from __future__ import annotations

import io
import re
import unicodedata

from raku_rag.domain.parsed_document import (
    ANCHOR_PAGE_BBOX,
    BLOCK_CAPTION,
    BLOCK_FOOTER,
    BLOCK_HEADER,
    BLOCK_HEADING,
    BLOCK_LIST_ITEM,
    BLOCK_PARAGRAPH,
    BLOCK_TABLE,
    BLOCK_TITLE,
    BLOCK_UNKNOWN,
    Block,
    IngestionInfo,
    Page,
    ParsedDocument,
    Provenance,
    ProviderRun,
    RouteTraceStep,
    SourceAnchor,
    Table,
    TableCell,
    TableColumn,
)

PROVIDER = "docling"

# Formats Docling is the first-choice structured parser for (§9.1). HTML is included so the adapter
# is verifiable without the (model-downloading) PDF pipeline.
DOCLING_CONTENT_TYPES = frozenset(
    {
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",  # pptx
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # docx
        "text/html",
        "image/png",
        "image/jpeg",
        "image/tiff",
    }
)

# DoclingDocument DocItemLabel value -> our block kind (§7.5). Unknown labels fall back to unknown.
_LABEL_TO_KIND = {
    "title": BLOCK_TITLE,
    "section_header": BLOCK_HEADING,
    "text": BLOCK_PARAGRAPH,
    "paragraph": BLOCK_PARAGRAPH,
    "list_item": BLOCK_LIST_ITEM,
    "caption": BLOCK_CAPTION,
    "page_header": BLOCK_HEADER,
    "page_footer": BLOCK_FOOTER,
    "footnote": BLOCK_FOOTER,
    "code": BLOCK_PARAGRAPH,
    "formula": BLOCK_PARAGRAPH,
    "table": BLOCK_TABLE,
}


def docling_available() -> bool:
    """True iff the optional ``docling`` package can be imported."""
    import importlib.util

    return importlib.util.find_spec("docling") is not None


def _norm(text: str) -> str:
    return re.sub(r"[ \t]+", " ", unicodedata.normalize("NFKC", text or "")).strip()


def _bbox_tuple(prov) -> tuple[float, float, float, float] | None:
    """Extract [l, t, r, b] from a Docling ProvenanceItem, defensively across versions."""
    bbox = getattr(prov, "bbox", None)
    if bbox is None:
        return None
    try:
        return (float(bbox.l), float(bbox.t), float(bbox.r), float(bbox.b))
    except (AttributeError, TypeError, ValueError):
        return None


def _first_prov(item):
    provs = getattr(item, "prov", None) or ()
    return provs[0] if provs else None


class DoclingStructuredParser:
    """Structured parser backed by Docling (opt-in), normalizing to ``ParsedDocument`` (§P1)."""

    provider = PROVIDER

    def __init__(self, *, content_types: frozenset[str] = DOCLING_CONTENT_TYPES) -> None:
        self._content_types = content_types
        self._converter = None  # lazy DocumentConverter (expensive to build)

    def supports(self, content_type: str) -> bool:
        return content_type in self._content_types

    # --- converter ------------------------------------------------------------------------------
    def _get_converter(self):
        if self._converter is None:
            from docling.document_converter import DocumentConverter

            self._converter = DocumentConverter()
        return self._converter

    def _provider_version(self) -> str:
        try:
            from importlib.metadata import version

            return version("docling")
        except Exception:  # pragma: no cover - defensive
            return ""

    # --- entrypoint -----------------------------------------------------------------------------
    def parse_structured(
        self, raw: bytes, content_type: str, *, document_id: str = "", filename: str = ""
    ) -> ParsedDocument:
        source = _source_info(raw, content_type, document_id=document_id, filename=filename)
        if not docling_available():
            return self._offline_fallback(raw, content_type, source)
        try:
            docling_doc = self._convert(raw, content_type, filename=filename)
        except Exception as exc:  # extraction failure is a normal state (§P4), not a crash
            return self._extraction_error(raw, content_type, source, reason=str(exc)[:200])
        return self._normalize(docling_doc, source)

    def _convert(self, raw: bytes, content_type: str, *, filename: str):
        from docling.datamodel.base_models import DocumentStream

        name = filename or f"upload{_ext_for(content_type)}"
        stream = DocumentStream(name=name, stream=io.BytesIO(raw))
        result = self._get_converter().convert(stream)
        return result.document

    # --- normalization: DoclingDocument -> ParsedDocument ---------------------------------------
    def _normalize(self, doc, source) -> ParsedDocument:
        version = self._provider_version()
        prov = Provenance(provider=PROVIDER, provider_version=version, route="docling_first")

        pages = _normalize_pages(doc)
        blocks, tables = _normalize_items(doc, prov)

        run = ProviderRun(
            provider=PROVIDER,
            provider_version=version,
            model_versions={"layout": "docling-layout", "table": "docling-tableformer"},
            status="success",
        )
        route_trace = (
            RouteTraceStep(stage="extract", provider=PROVIDER, result="accepted", reason="docling"),
        )
        return ParsedDocument(
            source=source,
            ingestion=IngestionInfo(),
            provider_runs=(run,),
            pages=pages,
            blocks=blocks,
            tables=tables,
            route_trace=route_trace,
        )

    # --- degraded paths -------------------------------------------------------------------------
    def _offline_fallback(self, raw: bytes, content_type: str, source) -> ParsedDocument:
        return _text_fallback(
            raw,
            source,
            result="unavailable",
            reason="docling_not_installed",
            route="docling_unavailable_fallback",
        )

    def _extraction_error(self, raw: bytes, content_type: str, source, *, reason: str):
        return _text_fallback(
            raw, source, result="error", reason=reason, route="docling_error_fallback"
        )


# --- module helpers ------------------------------------------------------------------------------
def _source_info(raw: bytes, content_type: str, *, document_id: str, filename: str):
    from raku_rag.domain.parsed_document import SourceInfo

    return SourceInfo(
        document_id=document_id, filename=filename, mime_type=content_type, size_bytes=len(raw)
    )


def _ext_for(content_type: str) -> str:
    return {
        "application/pdf": ".pdf",
        "text/html": ".html",
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/tiff": ".tiff",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    }.get(content_type, ".bin")


def _normalize_pages(doc) -> tuple[Page, ...]:
    pages_attr = getattr(doc, "pages", None)
    if not pages_attr:
        return ()
    out: list[Page] = []
    items = pages_attr.items() if hasattr(pages_attr, "items") else enumerate(pages_attr, start=1)
    for page_no, page in items:
        size = getattr(page, "size", None)
        width = int(getattr(size, "width", 0) or 0) if size else None
        height = int(getattr(size, "height", 0) or 0) if size else None
        out.append(Page(page_id=f"p_{page_no}", page_no=int(page_no), width=width, height=height))
    return tuple(out)


def _normalize_items(doc, prov) -> tuple[tuple[Block, ...], tuple[Table, ...]]:
    blocks: list[Block] = []
    tables: list[Table] = []
    order = 0

    iterate = getattr(doc, "iterate_items", None)
    if callable(iterate):
        for item, _level in iterate():
            block, table = _item_to_block(item, order, prov, doc)
            if block is not None:
                blocks.append(block)
                order += 1
            if table is not None:
                tables.append(table)
        return tuple(blocks), tuple(tables)

    # Fallback for older docling: texts + tables attributes.
    for item in getattr(doc, "texts", ()) or ():
        block, _ = _item_to_block(item, order, prov, doc)
        if block is not None:
            blocks.append(block)
            order += 1
    for item in getattr(doc, "tables", ()) or ():
        _, table = _item_to_block(item, order, prov, doc)
        if table is not None:
            tables.append(table)
    return tuple(blocks), tuple(tables)


def _label_value(item) -> str:
    label = getattr(item, "label", None)
    return str(getattr(label, "value", label) or "").lower()


def _item_to_block(item, order: int, prov, doc):
    label = _label_value(item)
    kind = _LABEL_TO_KIND.get(label, BLOCK_UNKNOWN)

    if kind == BLOCK_TABLE or hasattr(item, "data") and getattr(item, "data", None) is not None:
        table = _table_from_item(item, order, prov)
        if table is not None:
            first = _first_prov(item)
            block = Block(
                block_id=f"b_{order}",
                kind=BLOCK_TABLE,
                text=_table_text(item, doc),
                normalized_text=_table_text(item, doc),
                page_no=getattr(first, "page_no", None),
                bbox=_bbox_tuple(first),
                reading_order=order,
                source_anchor=_page_anchor(first),
                provenance=prov,
            )
            return block, table

    text = _norm(getattr(item, "text", "") or "")
    if not text:
        return None, None
    first = _first_prov(item)
    block = Block(
        block_id=f"b_{order}",
        kind=kind,
        text=text,
        normalized_text=text,
        page_no=getattr(first, "page_no", None),
        bbox=_bbox_tuple(first),
        reading_order=order,
        source_anchor=_page_anchor(first),
        provenance=prov,
    )
    return block, None


def _page_anchor(prov) -> SourceAnchor | None:
    if prov is None:
        return None
    page_no = getattr(prov, "page_no", None)
    bbox = _bbox_tuple(prov)
    if page_no is None and bbox is None:
        return None
    return SourceAnchor(type=ANCHOR_PAGE_BBOX, page_no=page_no, bbox=bbox)


def _table_text(item, doc) -> str:
    """A flat text rendering of a table for embedding (the structured cells stay in the Table)."""
    try:
        md = item.export_to_markdown(doc)
        if md:
            return _norm(md).replace(" | ", " | ")
    except Exception:
        pass
    return ""


def _table_from_item(item, order: int, prov) -> Table | None:
    data = getattr(item, "data", None)
    if data is None:
        return None
    grid = getattr(data, "grid", None)
    columns: list[TableColumn] = []
    cells: list[TableCell] = []
    if grid:
        for r_idx, row in enumerate(grid, start=1):
            for c_idx, cell in enumerate(row, start=1):
                cell_text = _norm(getattr(cell, "text", "") or "")
                is_header = bool(
                    getattr(cell, "column_header", False) or getattr(cell, "row_header", False)
                )
                if is_header and r_idx == 1:
                    columns.append(TableColumn(index=c_idx - 1, text=cell_text))
                cells.append(
                    TableCell(row=r_idx, col=c_idx, text=cell_text, is_header=is_header)
                )
    first = _first_prov(item)
    return Table(
        table_id=f"t_{order}",
        page_no=getattr(first, "page_no", None),
        bbox=_bbox_tuple(first),
        columns=tuple(columns),
        cells=tuple(cells),
        provenance=prov,
    )


def _text_fallback(raw: bytes, source, *, result: str, reason: str, route: str) -> ParsedDocument:
    """Deterministic degraded output when Docling can't run — decode text, flag it in route_trace."""
    text = raw.decode("utf-8", errors="replace")
    text = re.sub(r"[ \t]+", " ", unicodedata.normalize("NFKC", text))
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    prov = Provenance(provider=PROVIDER, method="text_fallback", route=route)
    blocks = tuple(
        Block(
            block_id=f"b_{i}",
            kind=BLOCK_PARAGRAPH,
            text=para,
            normalized_text=para,
            reading_order=i,
            provenance=prov,
        )
        for i, para in enumerate(p for p in text.split("\n\n") if p.strip())
    )
    run = ProviderRun(provider=PROVIDER, status=result)
    route_trace = (
        RouteTraceStep(stage="extract", provider=PROVIDER, result=result, reason=reason),
    )
    return ParsedDocument(
        source=source,
        ingestion=IngestionInfo(),
        provider_runs=(run,),
        blocks=blocks,
        route_trace=route_trace,
    )
