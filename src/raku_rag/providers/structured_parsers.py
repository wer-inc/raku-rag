"""ADR-018 §9 — normalize the existing (str-returning) parsers into ``ParsedDocument`` (Phase B2).

These are the FIRST producers of the canonical contract (before Docling, §9.1): the Text / DOCX /
Spreadsheet parsers we already ship, re-expressed as ``StructuredParser`` s that emit
``ParsedDocument`` with block kinds, spreadsheet cell anchors (§7.7, FR-MFG-002 preserved), and
per-object provenance. A hard invariant, asserted in tests, is that ``text_for_embedding()`` of the
structured output equals the legacy ``Parser.parse()`` string for the same bytes — so switching the
ingestion path onto ``ParsedDocument`` (B5) cannot silently change chunking / retrieval / citations.

stdlib + the same optional [manufacturing] deps the legacy parsers already use (python-docx /
openpyxl, imported lazily). No heavy/Docling dependency here.
"""

from __future__ import annotations

import io
import re
import unicodedata
from typing import Protocol

from raku_rag.domain.parsed_document import (
    ANCHOR_SPREADSHEET_CELL,
    BLOCK_PARAGRAPH,
    BLOCK_TABLE_CELL,
    BLOCK_TABLE_ROW,
    Block,
    IngestionInfo,
    ParsedDocument,
    Provenance,
    ProviderRun,
    SourceAnchor,
    SourceInfo,
    Table,
    TableCell,
    TableColumn,
)
from raku_rag.providers.parsers import (
    CSV_CONTENT_TYPES,
    DOCX_CONTENT_TYPE,
    XLSX_CONTENT_TYPE,
    cell_anchor,
    read_spreadsheet_sheets,
)

_TAG = re.compile(r"<[^>]+>")
_TEXT_SUPPORTED = {"text/plain", "text/markdown", "text/html"}


def _norm(text: str) -> str:
    return re.sub(r"[ \t]+", " ", unicodedata.normalize("NFKC", text)).strip()


class StructuredParser(Protocol):
    """Provider-agnostic parser that returns the canonical ``ParsedDocument`` (§P1)."""

    def supports(self, content_type: str) -> bool: ...

    def parse_structured(
        self,
        raw: bytes,
        content_type: str,
        *,
        document_id: str = "",
        filename: str = "",
    ) -> ParsedDocument: ...


def _source_and_run(
    raw: bytes,
    content_type: str,
    *,
    document_id: str,
    filename: str,
    provider: str,
) -> tuple[SourceInfo, ProviderRun]:
    source = SourceInfo(
        document_id=document_id,
        filename=filename,
        mime_type=content_type,
        size_bytes=len(raw),
    )
    return source, ProviderRun(provider=provider, status="success")


class TextStructuredParser:
    """text/markdown/html -> paragraph blocks (split on blank lines), NFKC-normalized like TextParser."""

    provider = "text_parser"

    def supports(self, content_type: str) -> bool:
        return content_type in _TEXT_SUPPORTED

    def parse_structured(
        self, raw: bytes, content_type: str, *, document_id: str = "", filename: str = ""
    ) -> ParsedDocument:
        text = raw.decode("utf-8", errors="replace")
        if content_type == "text/html":
            text = _TAG.sub(" ", text)
        text = unicodedata.normalize("NFKC", text)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()

        source, run = _source_and_run(
            raw, content_type, document_id=document_id, filename=filename, provider=self.provider
        )
        prov = Provenance(provider=self.provider, method="native_text")
        blocks = tuple(
            Block(
                block_id=f"b_{i}",
                kind=BLOCK_PARAGRAPH,
                text=para,
                normalized_text=para,
                reading_order=i,
                provenance=prov,
            )
            # Split on blank lines: joining the pieces back with "\n\n" reproduces ``text`` exactly.
            for i, para in enumerate(p for p in text.split("\n\n") if p.strip())
        )
        return ParsedDocument(
            source=source,
            ingestion=IngestionInfo(),
            provider_runs=(run,),
            blocks=blocks,
        )


class SpreadsheetStructuredParser:
    """XLSX/CSV -> one ``table_cell`` block per non-empty data cell with a spreadsheet-cell anchor.

    Preserves the exact ``"{sheet}!R{row}C{col} {header}: {value}"`` cell text (FR-MFG-002) AND adds a
    structured ``Table`` per sheet (§7.6/§7.7) so downstream can cite either the flat anchor or the
    row/col cell.
    """

    provider = "spreadsheet_parser"

    def supports(self, content_type: str) -> bool:
        return content_type == XLSX_CONTENT_TYPE or content_type in CSV_CONTENT_TYPES

    def parse_structured(
        self, raw: bytes, content_type: str, *, document_id: str = "", filename: str = ""
    ) -> ParsedDocument:
        sheets = read_spreadsheet_sheets(raw, content_type)
        source, run = _source_and_run(
            raw, content_type, document_id=document_id, filename=filename, provider=self.provider
        )
        prov = Provenance(provider=self.provider, method="cell_anchor")

        blocks: list[Block] = []
        tables: list[Table] = []
        order = 0
        for t_idx, (sheet, rows) in enumerate(sheets):
            if not rows:
                continue
            header = rows[0]
            columns = tuple(TableColumn(index=c, text=_norm(str(h))) for c, h in enumerate(header))
            cells: list[TableCell] = [
                TableCell(row=1, col=c + 1, text=_norm(str(h)), is_header=True)
                for c, h in enumerate(header)
            ]
            for r_idx, row in enumerate(rows[1:], start=2):
                for c_idx, value in enumerate(row, start=1):
                    cell = _norm(str(value))
                    if not cell:
                        continue
                    col_name = ""
                    if c_idx - 1 < len(header):
                        col_name = _norm(str(header[c_idx - 1]))
                    anchor = cell_anchor(sheet, r_idx, c_idx)
                    label = f"{col_name}: " if col_name else ""
                    cell_text = f"{anchor} {label}{cell}"
                    blocks.append(
                        Block(
                            block_id=f"cell_{sheet}_{r_idx}_{c_idx}",
                            kind=BLOCK_TABLE_CELL,
                            text=cell_text,
                            normalized_text=cell_text,
                            reading_order=order,
                            source_anchor=SourceAnchor(
                                type=ANCHOR_SPREADSHEET_CELL,
                                sheet=sheet,
                                row=r_idx,
                                col=c_idx,
                                header=col_name or None,
                            ),
                            provenance=prov,
                        )
                    )
                    cells.append(TableCell(row=r_idx, col=c_idx, text=cell))
                    order += 1
            tables.append(
                Table(
                    table_id=f"t_{t_idx}",
                    columns=columns,
                    cells=tuple(cells),
                    provenance=prov,
                )
            )
        return ParsedDocument(
            source=source,
            ingestion=IngestionInfo(),
            provider_runs=(run,),
            blocks=tuple(blocks),
            tables=tuple(tables),
        )


class DocxStructuredParser:
    """DOCX -> paragraph blocks + one ``table_row`` block per table row (mirrors DocxParser output)."""

    provider = "docx_parser"

    def supports(self, content_type: str) -> bool:
        return content_type == DOCX_CONTENT_TYPE

    def parse_structured(
        self, raw: bytes, content_type: str, *, document_id: str = "", filename: str = ""
    ) -> ParsedDocument:
        from docx import Document as _DocxDocument  # local import: optional [manufacturing] dep

        doc = _DocxDocument(io.BytesIO(raw))
        source, run = _source_and_run(
            raw, content_type, document_id=document_id, filename=filename, provider=self.provider
        )
        prov = Provenance(provider=self.provider, method="native_text")

        blocks: list[Block] = []
        order = 0
        for para in doc.paragraphs:
            text = _norm(para.text or "")
            if not text:
                continue
            blocks.append(
                Block(
                    block_id=f"b_{order}",
                    kind=BLOCK_PARAGRAPH,
                    text=text,
                    normalized_text=text,
                    reading_order=order,
                    provenance=prov,
                )
            )
            order += 1
        for table in doc.tables:
            for row in table.rows:
                row_cells = [(c.text or "").strip() for c in row.cells]
                line = " | ".join(cell for cell in row_cells if cell)
                line = _norm(line)
                if not line:
                    continue
                blocks.append(
                    Block(
                        block_id=f"b_{order}",
                        kind=BLOCK_TABLE_ROW,
                        text=line,
                        normalized_text=line,
                        reading_order=order,
                        provenance=prov,
                    )
                )
                order += 1
        return ParsedDocument(
            source=source,
            ingestion=IngestionInfo(),
            provider_runs=(run,),
            blocks=tuple(blocks),
        )


class CompositeStructuredParser:
    """Dispatch to the first structured delegate that ``supports`` the content type (mirrors §Composite)."""

    def __init__(self, parsers: tuple[StructuredParser, ...] | None = None) -> None:
        self._parsers = parsers or (
            TextStructuredParser(),
            DocxStructuredParser(),
            SpreadsheetStructuredParser(),
        )

    def supports(self, content_type: str) -> bool:
        return any(p.supports(content_type) for p in self._parsers)

    def parse_structured(
        self, raw: bytes, content_type: str, *, document_id: str = "", filename: str = ""
    ) -> ParsedDocument:
        for p in self._parsers:
            if p.supports(content_type):
                return p.parse_structured(
                    raw, content_type, document_id=document_id, filename=filename
                )
        raise ValueError(f"unsupported content_type: {content_type}")
