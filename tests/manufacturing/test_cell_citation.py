"""T023 — US2: XLSX/CSV cell-coordinate citation (FR-MFG-002, contracts §A / mfg-interfaces §1).

A spreadsheet (XLSX) and a CSV ledger are ingested. A query that hits a SPECIFIC cell must return a
citation whose location resolves to the right ``sheet`` / ``row`` / ``col`` — preserved through the
001 ingestion/chunk/citation path via the ``sheet!R{row}C{col}`` cell anchor that the
``SpreadsheetParser`` embeds and maps onto the 001 offset model.

LOAD-BEARING ASSERTION: the cell coordinate is PRESERVED and CORRECT — a query whose answer lives in
row R / column C of sheet S returns a citation that resolves to exactly ``S!R{R}C{C}`` (1-based
row/col, header row = R1). A different cell must resolve to a different anchor.

Cell-anchor contract the impl (T026/T030) must expose (any one is accepted, checked in priority
order): the spreadsheet-derived search result / answer citation exposes either
  - ``cell_anchor: str``  equal to ``"{sheet}!R{row}C{col}"``, or
  - structured ``sheet: str`` + ``row: int`` + ``col: int`` fields,
and the cited chunk's normalized text contains the same ``sheet!R{row}C{col}`` anchor token so the
001 ``Citation.text_range`` resolves to that cell range.

Fixtures generated PROGRAMMATICALLY in a tmp dir (openpyxl / stdlib csv). No committed binaries.

TDD: RED now because ``ManufacturingSystem.ingest_manufacturing_file`` and the cell-anchor surface
are unimplemented. Authoritative: FR-MFG-002, contracts/mfg-openapi.md §A, mfg-interfaces.md §1.
"""
from __future__ import annotations

import csv
import io
import re
import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook

from raku_rag.domain.models import ScopeType, SubjectType
from tests.manufacturing.helpers import T, claims, fresh, mfg_meta

XLSX_CT = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
CSV_CT = "text/csv"

# sheet!R{row}C{col} — header is row 1, columns are 1-based.
_ANCHOR = re.compile(r"([A-Za-z0-9_]+)!R(\d+)C(\d+)")


def write_xlsx(path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "alarms"
    ws.append(["equipment", "alarm", "remedy"])               # R1: header
    ws.append(["pump17", "E152", "replace the impeller seal"])  # R2
    ws.append(["fan04", "E311", "tighten the coupling bolt"])   # R3
    wb.save(str(path))


def write_csv(path: Path) -> None:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["part_no", "defect", "action"])              # R1: header
    w.writerow(["P900", "crack", "scrap the housing"])        # R2
    w.writerow(["P201", "burr", "deburr the flange edge"])    # R3
    path.write_text(buf.getvalue(), encoding="utf-8")


def resolve_anchor(system, principal, result) -> tuple[str, int, int]:
    """Resolve a search result / citation to (sheet, row, col) via the impl's cell-anchor surface.

    Accepts, in priority order: a ``cell_anchor`` string attribute; structured sheet/row/col
    attributes; otherwise parses the ``sheet!R{row}C{col}`` anchor from the cited chunk text.
    """
    anchor = getattr(result, "cell_anchor", None)
    if isinstance(anchor, str):
        m = _ANCHOR.search(anchor)
        if m:
            return m.group(1), int(m.group(2)), int(m.group(3))
    sheet = getattr(result, "sheet", None)
    row = getattr(result, "row", None)
    col = getattr(result, "col", None)
    if sheet is not None and row is not None and col is not None:
        return str(sheet), int(row), int(col)
    # Fall back to the cited chunk's normalized text (the anchor MUST be embedded there).
    chunk_id = getattr(result, "chunk_id", None)
    item = system._mvp.store._items.get(chunk_id) if chunk_id else None
    if item is not None:
        m = _ANCHOR.search(item[0].text)
        if m:
            return m.group(1), int(m.group(2)), int(m.group(3))
    raise AssertionError(
        "spreadsheet-derived result exposes no resolvable cell anchor (sheet!R{row}C{col})"
    )


class TestXlsxCellCitation(unittest.TestCase):
    def setUp(self) -> None:
        self.sys = fresh()
        self.sys.grant(T, ScopeType.COLLECTION, "c", SubjectType.USER, "op")
        self.op = claims(T, "op")
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "alarms.xlsx"
        write_xlsx(self.path)
        self.sys.ingest_manufacturing_file(
            tenant_id=T,
            collection_id="c",
            document_id="ledger_xlsx",
            path=str(self.path),
            content_type=XLSX_CT,
            metadata=mfg_meta(tenant_id=T, document_id="ledger_xlsx"),
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_cell_hit_resolves_to_correct_sheet_row_col(self) -> None:
        # The remedy text lives in sheet "alarms", row 2 (E152/pump17), col 3 (remedy).
        results = self.sys.search(self.op, "replace impeller seal")
        hits = [r for r in results if r.document_id == "ledger_xlsx"]
        self.assertTrue(hits, "the E152 remedy cell must be retrievable")
        sheet, row, col = resolve_anchor(self.sys, self.op, hits[0])
        self.assertEqual(sheet, "alarms")
        self.assertEqual((row, col), (2, 3), "cell coordinate must be preserved and correct")

    def test_different_cell_resolves_to_different_anchor(self) -> None:
        # The E311 remedy lives in row 3 — its anchor MUST differ from the row-2 cell.
        r2 = [r for r in self.sys.search(self.op, "replace impeller seal")
              if r.document_id == "ledger_xlsx"]
        r3 = [r for r in self.sys.search(self.op, "tighten coupling bolt")
              if r.document_id == "ledger_xlsx"]
        self.assertTrue(r2 and r3)
        _, row2, _ = resolve_anchor(self.sys, self.op, r2[0])
        _, row3, _ = resolve_anchor(self.sys, self.op, r3[0])
        self.assertEqual(row2, 2)
        self.assertEqual(row3, 3)
        self.assertNotEqual(row2, row3, "distinct cells must resolve to distinct coordinates")


class TestCsvCellCitation(unittest.TestCase):
    def setUp(self) -> None:
        self.sys = fresh()
        self.sys.grant(T, ScopeType.COLLECTION, "c", SubjectType.USER, "op")
        self.op = claims(T, "op")
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "defects.csv"
        write_csv(self.path)
        self.sys.ingest_manufacturing_file(
            tenant_id=T,
            collection_id="c",
            document_id="ledger_csv",
            path=str(self.path),
            content_type=CSV_CT,
            metadata=mfg_meta(tenant_id=T, document_id="ledger_csv"),
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_csv_cell_hit_resolves_to_correct_row_col(self) -> None:
        # "deburr the flange edge" is the action cell at row 3, col 3 (header row = R1).
        results = self.sys.search(self.op, "deburr flange edge")
        hits = [r for r in results if r.document_id == "ledger_csv"]
        self.assertTrue(hits, "the deburr action cell must be retrievable")
        sheet, row, col = resolve_anchor(self.sys, self.op, hits[0])
        self.assertEqual((row, col), (3, 3), "CSV cell coordinate must be preserved and correct")


if __name__ == "__main__":
    unittest.main()
