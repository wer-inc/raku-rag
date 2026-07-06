"""ADR-018 §4.2/§9.4 — OCR is an independent, pluggable provider (not Docling's built-in)."""

from __future__ import annotations

import importlib.util
import io
import unittest

from raku_rag.domain.parsed_document import BLOCK_PARAGRAPH, BLOCK_UNKNOWN
from raku_rag.providers.docling_parser import apply_external_ocr
from raku_rag.providers.ocr.pluggable import (
    OCR_PROVIDER_ENV,
    NoOpOcrProvider,
    OcrResult,
    RapidOcrProvider,
    select_ocr_provider,
)

_RAPIDOCR_READY = RapidOcrProvider().available()
_HAS_PIL = importlib.util.find_spec("PIL") is not None


class _FakeOcr:
    name = "fake"

    def __init__(self, text: str) -> None:
        self._text = text

    def available(self) -> bool:
        return True

    def ocr_image(self, image_png: bytes) -> OcrResult:
        return OcrResult(text=self._text, confidence=0.9, provider=self.name)


class SelectOcrProviderTest(unittest.TestCase):
    def test_default_is_noop_not_docling(self) -> None:
        self.assertIsInstance(select_ocr_provider(), NoOpOcrProvider)
        self.assertEqual(select_ocr_provider().name, "none")

    def test_explicit_name_selects_provider(self) -> None:
        self.assertIsInstance(select_ocr_provider("rapidocr"), RapidOcrProvider)

    def test_env_selects_provider(self) -> None:
        import os

        prev = os.environ.get(OCR_PROVIDER_ENV)
        os.environ[OCR_PROVIDER_ENV] = "rapidocr"
        try:
            self.assertEqual(select_ocr_provider().name, "rapidocr")
        finally:
            if prev is None:
                del os.environ[OCR_PROVIDER_ENV]
            else:
                os.environ[OCR_PROVIDER_ENV] = prev

    def test_unknown_name_falls_back_to_noop(self) -> None:
        self.assertIsInstance(select_ocr_provider("does-not-exist"), NoOpOcrProvider)

    def test_cloud_providers_registered_and_unavailable_without_creds(self) -> None:
        # §9.4 cloud candidates are selectable but report unavailable without SDK+creds (never crash
        # on find_spec of a missing dotted parent, e.g. google.cloud).
        g = select_ocr_provider("google_docai")
        a = select_ocr_provider("azure_docintel")
        self.assertEqual(g.name, "google_docai")
        self.assertEqual(a.name, "azure_docintel")
        self.assertFalse(g.available())
        self.assertFalse(a.available())

    def test_cloud_egress_gate_default_denied(self) -> None:
        import os

        from raku_rag.providers.ocr.pluggable import CLOUD_EGRESS_ENV, cloud_egress_allowed

        prev = os.environ.get(CLOUD_EGRESS_ENV)
        try:
            os.environ.pop(CLOUD_EGRESS_ENV, None)
            self.assertFalse(cloud_egress_allowed())
            os.environ[CLOUD_EGRESS_ENV] = "1"
            self.assertTrue(cloud_egress_allowed())
            os.environ[CLOUD_EGRESS_ENV] = "false"
            self.assertFalse(cloud_egress_allowed())
        finally:
            if prev is None:
                os.environ.pop(CLOUD_EGRESS_ENV, None)
            else:
                os.environ[CLOUD_EGRESS_ENV] = prev

    def test_noop_is_unavailable_and_empty(self) -> None:
        p = NoOpOcrProvider()
        self.assertFalse(p.available())
        self.assertEqual(p.ocr_image(b"x").text, "")


class ApplyExternalOcrTest(unittest.TestCase):
    def test_available_provider_fills_pages(self) -> None:
        blocks, steps = apply_external_ocr(
            [2, 3],
            ocr_provider=_FakeOcr("読取テキスト"),
            render=lambda page_no: b"PNGBYTES",
            start_order=5,
        )
        self.assertEqual([b.kind for b in blocks], [BLOCK_PARAGRAPH, BLOCK_PARAGRAPH])
        self.assertEqual(blocks[0].text, "読取テキスト")
        self.assertEqual(blocks[0].page_no, 2)
        self.assertEqual(blocks[0].provenance.provider, "fake")
        self.assertEqual(blocks[0].provenance.route, "external_ocr")
        self.assertTrue(all(s.result == "ocr_filled" for s in steps))

    def test_unavailable_provider_fails_loud_review_required(self) -> None:
        blocks, steps = apply_external_ocr(
            [4],
            ocr_provider=NoOpOcrProvider(),
            render=lambda page_no: b"PNG",
            start_order=0,
        )
        self.assertEqual(blocks[0].kind, BLOCK_UNKNOWN)
        self.assertEqual(blocks[0].quality.status, "review_required")
        self.assertIn("scanned_no_external_ocr", blocks[0].quality.reasons)
        self.assertEqual(steps[0].result, "review_required")


class VlmDraftFallbackTest(unittest.TestCase):
    def test_vlm_draft_used_when_ocr_yields_nothing(self) -> None:
        from raku_rag.providers.vlm_draft import CallableVlmDraftProvider

        vlm = CallableVlmDraftProvider(lambda img, page: f"drawing summary page {page}")
        blocks, steps = apply_external_ocr(
            [2],
            ocr_provider=NoOpOcrProvider(),
            render=lambda page_no: b"PNG",
            start_order=0,
            vlm_provider=vlm,
        )
        self.assertEqual(blocks[0].kind, "visual_summary")
        self.assertEqual(blocks[0].quality.status, "draft_visual")
        self.assertIn("vlm_output_unapproved", blocks[0].quality.reasons)
        self.assertIn("drawing summary", blocks[0].text)
        self.assertEqual(blocks[0].provenance.route, "vlm_draft")
        self.assertEqual(steps[0].result, "draft_visual")

    def test_review_required_when_neither_ocr_nor_vlm(self) -> None:
        from raku_rag.providers.vlm_draft import NoOpVlmDraftProvider, select_vlm_draft_provider

        self.assertIsInstance(select_vlm_draft_provider(), NoOpVlmDraftProvider)
        blocks, _ = apply_external_ocr(
            [2],
            ocr_provider=NoOpOcrProvider(),
            render=lambda page_no: b"PNG",
            start_order=0,
            vlm_provider=NoOpVlmDraftProvider(),
        )
        self.assertEqual(blocks[0].quality.status, "review_required")


@unittest.skipUnless(_RAPIDOCR_READY and _HAS_PIL, "rapidocr backend/PIL not installed")
class RapidOcrRealTest(unittest.TestCase):
    def _text_png(self, text: str) -> bytes:
        from PIL import Image, ImageDraw, ImageFont

        img = Image.new("RGB", (480, 140), "white")
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("DejaVuSans-Bold.ttf", 72)
        except Exception:
            font = ImageFont.load_default()
        draw.text((30, 30), text, fill="black", font=font)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    def test_rapidocr_reads_text_from_an_image(self) -> None:
        provider = RapidOcrProvider()
        self.assertTrue(provider.available())
        result = provider.ocr_image(self._text_png("HELLO"))
        self.assertEqual(result.provider, "rapidocr")
        self.assertTrue(result.text.strip(), "RapidOCR returned no text")


if __name__ == "__main__":
    unittest.main()
