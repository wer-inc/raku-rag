"""T065 - deterministic OCR provider for local visual RAG tests."""

from __future__ import annotations

from raku_rag.domain.models import BoundingBox, OcrTextRegion


def _decode_text(image: bytes) -> str:
    return image.decode("utf-8", errors="ignore").strip()


class DeterministicOcrEngine:
    """OCR adapter that reads text embedded in fixture bytes.

    Each non-empty line becomes an OCR region. Lines may start with ``OCR:``; the prefix is stripped.
    Real OCR adapters can replace this behind the same ``extract(image)`` boundary.
    """

    engine_version = "deterministic-ocr-v1"

    def extract(self, image: bytes) -> tuple[OcrTextRegion, ...]:
        text = _decode_text(image)
        if not text:
            return ()
        regions: list[OcrTextRegion] = []
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        for idx, line in enumerate(lines, start=1):
            if line.lower().startswith("ocr:"):
                line = line.split(":", 1)[1].strip()
            if line.lower().startswith("caption:"):
                continue
            regions.append(
                OcrTextRegion(
                    text=line,
                    confidence=1.0,
                    bbox=BoundingBox(x=0.05, y=min(0.9, 0.05 * idx), width=0.9, height=0.04),
                    page_number=1,
                )
            )
        return tuple(regions)


__all__ = ["DeterministicOcrEngine"]
