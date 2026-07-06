"""ADR-018 §13.2/§9.1 — the worker routes PDFs through Docling when structured ingestion is on."""

from __future__ import annotations

import dataclasses
import unittest

from raku_rag.app import MvpSystem
from raku_rag.core.config import Settings
from raku_rag.domain.models import ScopeType, SubjectType
from raku_rag.providers.docling_parser import docling_available
from raku_rag.workers.ingestion import IngestionExecutor, IngestionExecutionResult

T = "tenant_worker_pdf"


def _minimal_pdf(text: str) -> bytes:
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
    ]
    stream = b"BT /F1 18 Tf 72 700 Td (" + text.encode("latin-1") + b") Tj ET"
    objs.append(
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"
    )
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += str(i).encode() + b" 0 obj\n" + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 " + str(len(objs) + 1).encode() + b"\n0000000000 65535 f \n"
    for off in offsets:
        out += ("%010d 00000 n \n" % off).encode()
    out += (
        b"trailer\n<< /Size " + str(len(objs) + 1).encode() + b" /Root 1 0 R >>\n"
        b"startxref\n" + str(xref).encode() + b"\n%%EOF"
    )
    return bytes(out)


_RESULT = IngestionExecutionResult(status="succeeded", document_id="d", chunk_count=1)


class PdfRoutingTest(unittest.TestCase):
    """Routing decision only — stubs the two paths so no real parsing/deps are needed."""

    def _executor(self, *, structured_pdf: bool) -> tuple[IngestionExecutor, list]:
        class _FakeVisual:
            pass

        ex = IngestionExecutor(
            object(), visual_executor=_FakeVisual(), structured_pdf=structured_pdf
        )
        called: list[str] = []
        ex.execute_visual_document = lambda **k: called.append("visual") or _RESULT
        ex._execute_structured_or_text = lambda **k: called.append("structured") or _RESULT
        return ex, called

    def _run(self, ex):
        return ex.execute_document(
            tenant_id=T,
            collection_id="c",
            source_id="s",
            document_id="d",
            raw=b"%PDF-1.4",
            content_type="application/pdf",
        )

    def test_pdf_goes_to_structured_when_enabled(self) -> None:
        ex, called = self._executor(structured_pdf=True)
        self._run(ex)
        self.assertEqual(called, ["structured"])

    def test_pdf_goes_to_visual_when_disabled(self) -> None:
        ex, called = self._executor(structured_pdf=False)
        self._run(ex)
        self.assertEqual(called, ["visual"])


@unittest.skipUnless(docling_available(), "docling not installed")
class PdfViaDoclingTest(unittest.TestCase):
    def test_pdf_ingested_through_docling_carries_page_anchor(self) -> None:
        system = MvpSystem(settings=dataclasses.replace(Settings(), structured_ingest_enabled=True))
        system.grant(T, ScopeType.COLLECTION, "c", SubjectType.USER, "alice")
        executor = IngestionExecutor(system.structured_ingestion, structured_pdf=True)
        result = executor.execute_document(
            tenant_id=T,
            collection_id="c",
            source_id="src",
            document_id="pdfdoc",
            raw=_minimal_pdf("Safety Stop main power before service"),
            content_type="application/pdf",
        )
        self.assertEqual(result.status, "succeeded")
        self.assertGreaterEqual(result.chunk_count, 1)
        chunk = next(c for c, _ in system.store.iter_items() if c.document_id == "pdfdoc")
        self.assertEqual(chunk.metadata.get("anchor_type"), "page_bbox")


if __name__ == "__main__":
    unittest.main()
