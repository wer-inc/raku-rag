"""ADR-018 §11 — structure-aware chunking from ``ParsedDocument`` (Phase B3).

The legacy ``SentenceChunker`` flattens everything to a string and splits on sentences, which breaks
tables, cells, lists and form fields (§11.1). This produces chunks straight from ``ParsedDocument``
blocks so each chunk keeps its citation anchor(s), block kind, quality status, and enclosing heading
context (§11.2/§11.3) — nothing is re-flattened before chunking, so the anchor never drifts.

stdlib only. Additive: this does not yet replace the live ingestion chunker (that is B5).
"""

from __future__ import annotations

from dataclasses import dataclass

from raku_rag.domain.parsed_document import (
    BLOCK_CAPTION,
    BLOCK_FORM_FIELD,
    BLOCK_HEADING,
    BLOCK_LIST_ITEM,
    BLOCK_TABLE,
    BLOCK_TABLE_CELL,
    BLOCK_TABLE_ROW,
    BLOCK_TITLE,
    ParsedDocument,
    SourceAnchor,
)

# Chunk "kind" (§11.3): how the chunk was formed, for retrieval/display routing.
CHUNK_PARAGRAPH = "paragraph_chunk"
CHUNK_CELL = "cell_chunk"
CHUNK_TABLE = "table_chunk"
CHUNK_LIST = "list_chunk"
CHUNK_FORM = "form_chunk"

_HEADING_KINDS = frozenset({BLOCK_TITLE, BLOCK_HEADING})
_CELL_KINDS = frozenset({BLOCK_TABLE_CELL})
_TABLE_KINDS = frozenset({BLOCK_TABLE, BLOCK_TABLE_ROW})
_LIST_KINDS = frozenset({BLOCK_LIST_ITEM})
_FORM_KINDS = frozenset({BLOCK_FORM_FIELD})


@dataclass(frozen=True)
class StructuredChunk:
    """A citation-preserving chunk derived from one or more ParsedDocument blocks (§11.3)."""

    text_for_embedding: str
    display_text: str
    kind: str
    source_block_ids: tuple[str, ...] = ()
    source_anchors: tuple[SourceAnchor, ...] = ()
    quality_status: str = "accepted"
    quality_reasons: tuple[str, ...] = ()
    heading_path: tuple[str, ...] = ()
    min_block_confidence: float | None = None


def _kind_for_block(block_kind: str) -> str:
    if block_kind in _CELL_KINDS:
        return CHUNK_CELL
    if block_kind in _TABLE_KINDS:
        return CHUNK_TABLE
    if block_kind in _LIST_KINDS:
        return CHUNK_LIST
    if block_kind in _FORM_KINDS:
        return CHUNK_FORM
    return CHUNK_PARAGRAPH


def chunk_parsed_document(parsed: ParsedDocument) -> list[StructuredChunk]:
    """Yield one chunk per content block, threading the enclosing heading as context (§11.2).

    Headings/titles are NOT emitted as their own chunks; they become ``heading_path`` context on the
    blocks that follow (mirrors the SentenceChunker's heading_path so retrieval/citation keep working).
    Tables, cells, list items and form fields each stay whole so their structure/anchor survive.
    """

    chunks: list[StructuredChunk] = []
    heading_path: tuple[str, ...] = ()

    for block in parsed.ordered_blocks():
        text = block.embedding_text.strip()
        if not text:
            continue

        if block.kind in _HEADING_KINDS:
            # A heading updates the running context; a title resets the path, a heading appends.
            if block.kind == BLOCK_TITLE:
                heading_path = (text,)
            else:
                heading_path = (*heading_path, text)
            continue
        if block.kind == BLOCK_CAPTION:
            # Captions ride with the surrounding content but do not alter heading context.
            pass

        anchors = (block.source_anchor,) if block.source_anchor is not None else ()
        chunks.append(
            StructuredChunk(
                text_for_embedding=text,
                display_text=block.text or text,
                kind=_kind_for_block(block.kind),
                source_block_ids=(block.block_id,),
                source_anchors=anchors,
                quality_status=block.quality.status,
                quality_reasons=tuple(block.quality.reasons),
                heading_path=heading_path,
                min_block_confidence=block.confidence,
            )
        )
    return chunks
