"""ADR-018 §9.1 — DoclingStructuredParser (Phase B4).

The real-Docling test is skipped where the optional dep is absent (e.g. the stdlib CI gate); the
offline-fallback test runs everywhere and pins the degraded behaviour so an env without Docling never
crashes ingestion.
"""

from __future__ import annotations

import unittest

from raku_rag.domain.parsed_document import (
    BLOCK_PARAGRAPH,
    BLOCK_TABLE,
    BLOCK_TITLE,
    PARSED_DOCUMENT_SCHEMA_VERSION,
)
from raku_rag.providers import docling_parser
from raku_rag.providers.docling_parser import (
    DoclingStructuredParser,
    _normalize_figures,
    _quality_from_confidence,
    docling_available,
)

_HTML = (
    b"<html><body><h1>Safety Procedure</h1>"
    b"<p>Stop the main power before work.</p>"
    b"<table><tr><th>Item</th><th>Value</th></tr>"
    b"<tr><td>Voltage</td><td>200V</td></tr></table></body></html>"
)


class DoclingSupportTest(unittest.TestCase):
    def test_supports_pdf_and_office_and_images(self) -> None:
        p = DoclingStructuredParser()
        self.assertTrue(p.supports("application/pdf"))
        self.assertTrue(p.supports("text/html"))
        self.assertTrue(p.supports("image/png"))
        self.assertFalse(p.supports("text/csv"))


class DoclingOfflineFallbackTest(unittest.TestCase):
    def setUp(self) -> None:
        self._orig = docling_parser.docling_available
        docling_parser.docling_available = lambda: False

    def tearDown(self) -> None:
        docling_parser.docling_available = self._orig

    def test_fallback_decodes_text_and_records_route_trace(self) -> None:
        doc = DoclingStructuredParser().parse_structured(
            b"line one\n\nline two", "application/pdf", document_id="d1"
        )
        self.assertEqual(doc.schema_version, PARSED_DOCUMENT_SCHEMA_VERSION)
        self.assertEqual([b.text for b in doc.blocks], ["line one", "line two"])
        self.assertEqual(doc.route_trace[0].result, "unavailable")
        self.assertEqual(doc.route_trace[0].reason, "docling_not_installed")
        self.assertEqual(doc.provider_runs[0].provider, "docling")
        self.assertEqual(doc.blocks[0].provenance.route, "docling_unavailable_fallback")


class _FakeConfidence:
    def __init__(self, mean, low, layout) -> None:
        self.mean_score = mean
        self.low_score = low
        self.layout_score = layout


class _FakePicture:
    def __init__(self) -> None:
        self.prov = ()

    def caption_text(self, doc) -> str:
        return "Figure 1: pump assembly"


class _FakeDocWithPicture:
    pictures = (_FakePicture(),)


class DoclingQualityAndFiguresTest(unittest.TestCase):
    def test_quality_from_confidence_builds_dimension_vector(self) -> None:
        q = _quality_from_confidence(_FakeConfidence(0.78, 0.58, 0.55))
        self.assertEqual(q.metrics["ocr_confidence_p50"], 0.78)
        self.assertEqual(q.metrics["ocr_confidence_p10"], 0.58)
        self.assertEqual(q.metrics["layout_confidence"], 0.55)
        self.assertEqual(q.status, "accepted")

    def test_quality_nan_scores_are_dropped(self) -> None:
        q = _quality_from_confidence(_FakeConfidence(float("nan"), float("nan"), float("nan")))
        self.assertEqual(dict(q.metrics), {})

    def test_low_confidence_flags_warnings(self) -> None:
        q = _quality_from_confidence(_FakeConfidence(0.5, 0.1, 0.4))
        self.assertEqual(q.status, "accepted_with_warnings")
        self.assertIn("low_confidence_regions", q.reasons)

    def test_none_confidence_is_plain_accepted(self) -> None:
        self.assertEqual(_quality_from_confidence(None).status, "accepted")

    def test_normalize_figures_captures_pictures(self) -> None:
        from raku_rag.domain.parsed_document import Provenance

        figs = _normalize_figures(_FakeDocWithPicture(), Provenance(provider="docling"))
        self.assertEqual(len(figs), 1)
        self.assertEqual(figs[0].caption, "Figure 1: pump assembly")


@unittest.skipUnless(docling_available(), "docling not installed")
class DoclingRealConversionTest(unittest.TestCase):
    def test_html_normalizes_to_parsed_document_with_structure(self) -> None:
        doc = DoclingStructuredParser().parse_structured(
            _HTML, "text/html", document_id="d1", filename="proc.html"
        )
        kinds = [b.kind for b in doc.blocks]
        self.assertIn(BLOCK_TITLE, kinds)
        self.assertIn(BLOCK_PARAGRAPH, kinds)
        self.assertIn(BLOCK_TABLE, kinds)

        # provenance / run recorded (§7.2 / §13.3)
        run = doc.provider_runs[0]
        self.assertEqual(run.provider, "docling")
        self.assertNotEqual(run.provider_version, "")
        self.assertEqual(run.model_versions.get("ocr_provider"), "none")
        # A5 §13.3: real version + config hash + timestamps recorded for reindex/audit.
        self.assertIn(run.provider_version, run.model_versions["layout"])
        self.assertTrue(run.config_hash.startswith("sha256:"))
        self.assertTrue(run.started_at and run.finished_at)

        # §4.2/§9.4: Docling's built-in OCR is disabled and OCR is owned by an independent provider,
        # recorded in the route_trace.
        config_steps = [s for s in doc.route_trace if s.stage == "config"]
        self.assertTrue(config_steps)
        self.assertEqual(config_steps[0].result, "docling_ocr_disabled")
        self.assertEqual(config_steps[0].reason, "external_ocr=none")
        self.assertTrue(any(s.result == "accepted" for s in doc.route_trace))

        # table structure preserved with header detection (§7.6)
        self.assertEqual(len(doc.tables), 1)
        table = doc.tables[0]
        header_cells = {c.text for c in table.cells if c.is_header}
        self.assertEqual(header_cells, {"Item", "Value"})
        body = {(c.text) for c in table.cells if not c.is_header}
        self.assertIn("Voltage", body)
        self.assertIn("200V", body)

        # canonical derived text carries the content
        emb = doc.text_for_embedding()
        self.assertIn("Safety Procedure", emb)
        self.assertIn("Stop the main power before work.", emb)


if __name__ == "__main__":
    unittest.main()
