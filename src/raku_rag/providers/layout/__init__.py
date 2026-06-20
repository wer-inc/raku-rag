"""T066 - deterministic layout extractor for visual assets."""

from __future__ import annotations

import hashlib
from typing import Sequence

from raku_rag.domain.models import LayoutRegion, OcrTextRegion
from raku_rag.providers.ocr import DeterministicOcrEngine


class DeterministicLayoutExtractor:
    extractor_version = "deterministic-layout-v1"

    def __init__(self, ocr: DeterministicOcrEngine | None = None) -> None:
        self._ocr = ocr or DeterministicOcrEngine()

    def extract(
        self,
        image: bytes,
        *,
        tenant_id: str = "",
        collection_id: str = "",
        document_id: str = "",
        asset_id: str = "",
        ocr_regions: Sequence[OcrTextRegion] | None = None,
    ) -> tuple[LayoutRegion, ...]:
        if not asset_id:
            asset_id = "asset_" + hashlib.sha256(image).hexdigest()[:12]
        regions = tuple(ocr_regions) if ocr_regions is not None else self._ocr.extract(image)
        return tuple(
            LayoutRegion(
                tenant_id=tenant_id,
                collection_id=collection_id,
                document_id=document_id,
                asset_id=asset_id,
                region_id=f"{asset_id}:region:{idx}",
                bbox=region.bbox,
                page_number=region.page_number,
                region_type="text",
                heading_path=("visual",),
                ocr_text=region.text,
            )
            for idx, region in enumerate(regions, start=1)
        )


__all__ = ["DeterministicLayoutExtractor"]
