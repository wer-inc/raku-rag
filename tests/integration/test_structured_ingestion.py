"""ADR-018 Phase B5 — StructuredIngestionService end to end over the in-memory stack.

Proves the structured path indexes into the SAME store the retrieval service reads, preserves cell
anchors, feeds the Phase A quality gate (review_required blocks are quarantined out of retrieval), and
hands the raw provider output to the sink.
"""

from __future__ import annotations

import unittest
from unittest import mock

from raku_rag.app import MvpSystem
from raku_rag.domain.models import QueryProfile, ScopeType, SubjectType
from raku_rag.providers.docling_parser import DoclingStructuredParser, docling_available
from raku_rag.providers.structured_parsers import CompositeStructuredParser
from raku_rag.services.ingestion_quality import (
    EXTRACTION_QUALITY_STATUS_KEY,
    QUALITY_STATUS_REVIEW_REQUIRED,
    is_high_risk_citation_quality_eligible,
)
from raku_rag.services.structured_ingestion import (
    StructuredIngestionService,
    build_structured_parser,
)
from tests.helpers import claims

T = "tenant_s"


class StructuredIngestionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.sys = MvpSystem()
        self.sys.grant(T, ScopeType.COLLECTION, "c", SubjectType.USER, "alice")
        self.alice = claims(T, "alice")
        self.raw_captured: dict[str, dict] = {}
        self.svc = StructuredIngestionService(
            store=self.sys.store,
            embedder=self.sys.embedder,
            structured_parser=CompositeStructuredParser(),
            registry=self.sys.registry,
            metrics=self.sys.metrics,
            tracer=self.sys.tracer,
            raw_sink=lambda doc_id, raw: self.raw_captured.__setitem__(doc_id, raw),
        )

    def test_expected_language_is_env_configurable(self) -> None:
        # §8.3 language_consistency: a JP deployment turns the gate on with RAKU_EXPECTED_LANGUAGE=ja
        # (no code change); unset keeps it off so English tenants are unaffected.
        with mock.patch.dict("os.environ", {"RAKU_EXPECTED_LANGUAGE": "ja"}):
            parser = build_structured_parser()
        docling = parser._parsers[0]  # type: ignore[attr-defined]
        self.assertIsInstance(docling, DoclingStructuredParser)
        self.assertEqual(docling._expected_language, "ja")
        default_parser = build_structured_parser()
        self.assertEqual(default_parser._parsers[0]._expected_language, "")  # type: ignore[attr-defined]

    def test_default_parser_routes_docx_to_docling_first(self) -> None:
        parser = build_structured_parser()
        doc = parser.parse_structured(
            b"not a real docx but enough to prove routing",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            document_id="docx-route",
        )
        self.assertEqual(doc.provider_runs[0].provider, "docling")
        self.assertEqual(doc.quality.status, "review_required")

    def _stored(self, document_id: str):
        for chunk, _v in self.sys.store.iter_items():
            if chunk.document_id == document_id:
                yield chunk

    def _quarantined(self, document_id: str):
        for chunk, _v in self.sys.store.iter_quarantine_items():
            if chunk.document_id == document_id:
                yield chunk

    def test_csv_ingest_indexes_retrievable_cells_with_anchors(self) -> None:
        csv = b"item,remedy\nPump P-12,replace valve\nPump P-13,tighten bolt"
        job = self.svc.ingest(
            tenant_id=T,
            collection_id="c",
            source_id="s",
            document_id="sheet1",
            raw=csv,
            content_type="text/csv",
        )
        self.assertEqual(job.status, "succeeded", job.failure_reason)

        # raw provider output was handed to the sink (§P2)
        self.assertIn("sheet1", self.raw_captured)
        self.assertEqual(self.raw_captured["sheet1"]["schema_version"], "parsed_document.v1")

        # cell anchor metadata is present
        cells = list(self._stored("sheet1"))
        self.assertTrue(cells)
        anchored = [c for c in cells if c.metadata.get("cell_sheet") == "sheet1"]
        self.assertTrue(anchored)
        self.assertIn("sheet1!R2C1", anchored[0].text)
        self.assertEqual(
            anchored[0].metadata["provider_details"][0]["provider"], "spreadsheet_parser"
        )
        self.assertEqual(
            anchored[0].metadata["block_provider_details"][0]["provider"], "spreadsheet_parser"
        )

        # and the content is retrievable through the normal retrieval service
        result = self.sys.retrieval.retrieve(
            self.alice,
            "Pump P-12 remedy replace valve",
            QueryProfile(top_k=10, rerank_enabled=False),
        )
        self.assertIn("sheet1", {item.chunk.document_id for item in result})

    def test_mojibake_block_is_quarantined_out_of_retrieval(self) -> None:
        good = "Pump P-20 maintenance interval is ninety days. " * 3
        self.svc.ingest(
            tenant_id=T,
            collection_id="c",
            source_id="s",
            document_id="good",
            raw=good.encode(),
            content_type="text/plain",
        )
        broken = "Pump P-20 maintenance " + "�" * 40
        job = self.svc.ingest(
            tenant_id=T,
            collection_id="c",
            source_id="s",
            document_id="broken",
            raw=broken.encode("utf-8"),
            content_type="text/plain",
        )
        self.assertEqual(job.status, "succeeded", job.failure_reason)
        self.assertEqual(list(self._stored("broken")), [])
        broken_chunks = list(self._quarantined("broken"))
        self.assertTrue(broken_chunks)
        self.assertTrue(
            all(
                c.metadata[EXTRACTION_QUALITY_STATUS_KEY] == QUALITY_STATUS_REVIEW_REQUIRED
                for c in broken_chunks
            )
        )

        result = self.sys.retrieval.retrieve(
            self.alice,
            "Pump P-20 maintenance interval",
            QueryProfile(top_k=10, rerank_enabled=False),
        )
        docs = {item.chunk.document_id for item in result}
        self.assertIn("good", docs)
        self.assertNotIn("broken", docs)

    def test_clean_text_ingest_stays_high_risk_eligible(self) -> None:
        # Regression: text_parser has no page/bbox anchor concept at all, so a clean plain-text chunk
        # must not be permanently excluded from high-risk citation for lacking one (§11.4 anchor check
        # is scoped to parsers that CAN produce an anchor — docling/spreadsheet — not text/docx).
        self.svc.ingest(
            tenant_id=T,
            collection_id="c",
            source_id="s",
            document_id="clean_text",
            raw=b"Stop the main power before servicing pump P-12. Torque the bolts to 45 Nm.",
            content_type="text/plain",
        )
        chunks = list(self._stored("clean_text"))
        self.assertTrue(chunks)
        self.assertEqual(chunks[0].metadata.get("parser_provider"), "text_parser")
        self.assertTrue(is_high_risk_citation_quality_eligible(chunks[0].metadata))

    @unittest.skipUnless(docling_available(), "docling not installed")
    def test_docling_html_ingest_is_retrievable_with_provenance(self) -> None:
        svc = StructuredIngestionService(
            store=self.sys.store,
            embedder=self.sys.embedder,
            structured_parser=DoclingStructuredParser(),
            registry=self.sys.registry,
        )
        html = (
            b"<html><body><h1>Torque Spec</h1>"
            b"<p>Tighten the flange bolt to two hundred newton meters.</p></body></html>"
        )
        job = svc.ingest(
            tenant_id=T,
            collection_id="c",
            source_id="s",
            document_id="html1",
            raw=html,
            content_type="text/html",
            filename="spec.html",
        )
        self.assertEqual(job.status, "succeeded", job.failure_reason)
        doc = self.sys.registry.get(T, "html1")
        self.assertEqual(doc.metadata["parser_provider"], "docling")

        result = self.sys.retrieval.retrieve(
            self.alice,
            "flange bolt torque newton meters",
            QueryProfile(top_k=10, rerank_enabled=False),
        )
        self.assertIn("html1", {item.chunk.document_id for item in result})


if __name__ == "__main__":
    unittest.main()
