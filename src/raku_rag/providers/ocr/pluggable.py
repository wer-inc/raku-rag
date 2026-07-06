"""ADR-018 §4.2 / §9.4 — OCR as an independent, pluggable provider (NOT Docling's built-in OCR).

The ADR is explicit: Docling is the first-choice *structure* parser, but the responsibility for
(Japanese) OCR must NOT sit inside Docling. OCR is managed as its own provider so the engine can be
selected/swapped by config and evaluated on its own (§9.4 candidates: PaddleOCR / Google Document AI
/ Azure DI / Azure Vision / Tesseract-jpn / RapidOCR; Textract is a supplementary, non-default
provider per §9.5, wired separately in providers/aws_visual.py). This is distinct from the sibling
``DeterministicOcrEngine`` (the offline visual-RAG test stub) in this package.

Heavy engines are opt-in and imported lazily, so the Tier A gate stays stdlib-only. The default
provider is ``none`` (NoOp): with Docling's own OCR disabled and no external OCR selected, a scanned /
text-less page is FLAGGED for review rather than silently OCR'd — Phase A's false-accept-first stance
(§P5). Selecting a real engine (``RAKU_OCR_PROVIDER=rapidocr`` etc.) opts into automatic OCR.
"""

from __future__ import annotations

import importlib.util
import os
from dataclasses import dataclass
from typing import Protocol

OCR_PROVIDER_ENV = "RAKU_OCR_PROVIDER"
OCR_PROVIDER_NONE = "none"


def _spec_exists(name: str) -> bool:
    """find_spec that returns False (not raises) when a dotted parent package is absent."""
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


@dataclass(frozen=True)
class OcrResult:
    text: str = ""
    confidence: float | None = None
    provider: str = OCR_PROVIDER_NONE


class OcrProvider(Protocol):
    name: str

    def available(self) -> bool: ...

    def ocr_image(self, image_png: bytes) -> OcrResult: ...


class NoOpOcrProvider:
    """The default: no external OCR. Docling structure only; scanned pages are flagged, not guessed."""

    name = OCR_PROVIDER_NONE

    def available(self) -> bool:
        return False

    def ocr_image(self, image_png: bytes) -> OcrResult:
        return OcrResult(provider=self.name)


class RapidOcrProvider:
    """RapidOCR — local/self-hosted multilingual OCR incl. Japanese (§9.4). Lazy import."""

    name = "rapidocr"

    def __init__(self) -> None:
        self._engine = None

    def available(self) -> bool:
        has_pkg = (
            importlib.util.find_spec("rapidocr") is not None
            or importlib.util.find_spec("rapidocr_onnxruntime") is not None
        )
        # RapidOCR needs an inference backend; without it, report unavailable so the caller fails
        # loud (review_required) instead of crashing mid-parse.
        has_backend = importlib.util.find_spec("onnxruntime") is not None
        return has_pkg and has_backend

    def _get_engine(self):
        if self._engine is None:
            try:
                from rapidocr import RapidOCR  # rapidocr >= 2
            except ImportError:  # pragma: no cover - older package name
                from rapidocr_onnxruntime import RapidOCR
            self._engine = RapidOCR()
        return self._engine

    def ocr_image(self, image_png: bytes) -> OcrResult:
        if not self.available():
            return OcrResult(provider=self.name)
        result = self._get_engine()(image_png)
        text, score = _parse_rapidocr_result(result)
        return OcrResult(text=text, confidence=score, provider=self.name)


class TesseractOcrProvider:
    """Tesseract-jpn — low-cost local fallback OCR (§9.4). Lazy; needs pytesseract + the binary."""

    name = "tesseract"

    def available(self) -> bool:
        if importlib.util.find_spec("pytesseract") is None:
            return False
        import shutil

        return shutil.which("tesseract") is not None

    def ocr_image(self, image_png: bytes) -> OcrResult:
        if not self.available():
            return OcrResult(provider=self.name)
        import io

        import pytesseract
        from PIL import Image

        text = pytesseract.image_to_string(Image.open(io.BytesIO(image_png)), lang="jpn")
        return OcrResult(text=text.strip(), provider=self.name)


class PaddleOcrProvider:
    """PaddleOCR — multilingual incl. Japanese (§9.4). Lazy; heavy optional dep."""

    name = "paddleocr"

    def __init__(self) -> None:
        self._engine = None

    def available(self) -> bool:
        return importlib.util.find_spec("paddleocr") is not None

    def _get_engine(self):
        if self._engine is None:
            from paddleocr import PaddleOCR

            self._engine = PaddleOCR(use_angle_cls=True, lang="japan", show_log=False)
        return self._engine

    def ocr_image(self, image_png: bytes) -> OcrResult:
        if not self.available():
            return OcrResult(provider=self.name)
        import io

        import numpy as np
        from PIL import Image

        arr = np.array(Image.open(io.BytesIO(image_png)).convert("RGB"))
        rows = self._get_engine().ocr(arr, cls=True) or []
        lines = [line[1][0] for page in rows for line in (page or [])]
        return OcrResult(text="\n".join(lines).strip(), provider=self.name)


class GoogleDocumentAiOcrProvider:
    """Google Document AI Enterprise OCR (§9.4) — 200+ langs incl. Japanese + handwriting. Cloud.

    Opt-in; sends document bytes to Google, so it is gated by tenant data-egress policy (§19). Requires
    google-cloud-documentai + GOOGLE_DOCAI_PROCESSOR (full processor resource name)."""

    name = "google_docai"

    def available(self) -> bool:
        return (
            _spec_exists("google.cloud.documentai")
            and bool(os.environ.get("GOOGLE_DOCAI_PROCESSOR"))
        )

    def ocr_image(self, image_png: bytes) -> OcrResult:
        if not self.available():
            return OcrResult(provider=self.name)
        from google.cloud import documentai  # lazy, opt-in

        client = documentai.DocumentProcessorServiceClient()
        raw = documentai.RawDocument(content=image_png, mime_type="image/png")
        name = os.environ["GOOGLE_DOCAI_PROCESSOR"]
        result = client.process_document(request=documentai.ProcessRequest(name=name, raw_document=raw))
        return OcrResult(text=(result.document.text or "").strip(), provider=self.name)


class AzureDocumentIntelligenceOcrProvider:
    """Azure Document Intelligence layout/OCR (§9.4) — Japanese print + handwriting, tables. Cloud.

    Opt-in; §19 data-egress policy applies. Requires azure-ai-documentintelligence +
    AZURE_DOCINTEL_ENDPOINT + AZURE_DOCINTEL_KEY."""

    name = "azure_docintel"

    def available(self) -> bool:
        return (
            _spec_exists("azure.ai.documentintelligence")
            and bool(os.environ.get("AZURE_DOCINTEL_ENDPOINT"))
            and bool(os.environ.get("AZURE_DOCINTEL_KEY"))
        )

    def ocr_image(self, image_png: bytes) -> OcrResult:
        if not self.available():
            return OcrResult(provider=self.name)
        from azure.ai.documentintelligence import DocumentIntelligenceClient  # lazy, opt-in
        from azure.core.credentials import AzureKeyCredential

        client = DocumentIntelligenceClient(
            endpoint=os.environ["AZURE_DOCINTEL_ENDPOINT"],
            credential=AzureKeyCredential(os.environ["AZURE_DOCINTEL_KEY"]),
        )
        poller = client.begin_analyze_document("prebuilt-read", body=image_png)
        return OcrResult(text=(poller.result().content or "").strip(), provider=self.name)


# §9.4 candidate registry. Cloud providers (Google Document AI / Azure DI) are opt-in and gated by
# tenant data-egress policy (§19). Textract stays a supplementary, non-default provider (§9.5, wired
# in providers/aws_visual.py). The default remains "none" — never Docling's built-in OCR (§4.2).
OCR_PROVIDERS: dict[str, type] = {
    OCR_PROVIDER_NONE: NoOpOcrProvider,
    "rapidocr": RapidOcrProvider,
    "tesseract": TesseractOcrProvider,
    "paddleocr": PaddleOcrProvider,
    "google_docai": GoogleDocumentAiOcrProvider,
    "azure_docintel": AzureDocumentIntelligenceOcrProvider,
}


def select_ocr_provider(name: str | None = None) -> OcrProvider:
    """Pick the OCR provider by explicit name or the ``RAKU_OCR_PROVIDER`` env (default: none).

    The default is deliberately NOT Docling's built-in OCR — that is the whole point of §4.2/§9.4.
    """

    chosen = (name or os.environ.get(OCR_PROVIDER_ENV) or OCR_PROVIDER_NONE).strip().lower()
    factory = OCR_PROVIDERS.get(chosen, NoOpOcrProvider)
    return factory()


def _parse_rapidocr_result(result: object) -> tuple[str, float | None]:
    """Extract (text, mean_confidence) from RapidOCR output across versions."""

    # rapidocr >= 3 returns an object with .txts / .scores.
    txts = getattr(result, "txts", None)
    if txts is not None:
        scores = getattr(result, "scores", None) or ()
        text = "\n".join(str(t) for t in txts if t)
        conf = (sum(scores) / len(scores)) if scores else None
        return text.strip(), conf
    # older: (list_of[box, text, score], elapse) or None
    if isinstance(result, tuple) and result and isinstance(result[0], list):
        rows = result[0]
        text = "\n".join(str(r[1]) for r in rows if len(r) >= 2)
        scores = [float(r[2]) for r in rows if len(r) >= 3]
        conf = (sum(scores) / len(scores)) if scores else None
        return text.strip(), conf
    return "", None
