"""T069 - deterministic VLM provider for visual evidence."""

from __future__ import annotations

import re
from typing import Sequence

from raku_rag.core.text import content_terms
from raku_rag.domain.models import LayoutRegion

_SENT = re.compile(r"[^。．.!?！？\n]+[。．.!?！？]?")


class ExtractiveVLMProvider:
    """Generates from OCR/layout region text only.

    ``generated_caption_text`` is deliberately ignored: captions may help retrieval, but they are not
    primary evidence for visual answers (FR-048).
    """

    model = "extractive-vlm-v1"

    def generate(self, query: str, *, visual_regions: Sequence[LayoutRegion]) -> str:
        q = content_terms(query)
        best: list[tuple[int, str]] = []
        for region in visual_regions:
            for sentence in _SENT.findall(region.ocr_text or ""):
                sentence = sentence.strip()
                if not sentence:
                    continue
                overlap = len(q & content_terms(sentence))
                if overlap:
                    best.append((overlap, sentence))
        if not best:
            return ""
        best.sort(key=lambda item: item[0], reverse=True)
        return " ".join(sentence for _, sentence in best[:2])


__all__ = ["ExtractiveVLMProvider"]
