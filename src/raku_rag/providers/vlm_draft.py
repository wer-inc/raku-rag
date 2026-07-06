"""ADR-018 §10 / Phase D — VLM draft fallback for difficult pages (drawings, handwriting, scans).

A VLM is NOT a canonical extractor (§10.1): its output is always ``draft_visual`` — excluded from
retrieval and high-risk citation until a human approves it (Phase A already treats draft_visual as
retrieval-blocking and a review-queue item). This module is the pluggable draft producer; the default
is a NoOp (unavailable), and real Claude/Gemini vision providers are opt-in (API keys, §19 egress
policy). The draft carries crop/bbox + prompt/model version so a reviewer can verify it (§10.2).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol

VLM_PROVIDER_ENV = "RAKU_VLM_DRAFT_PROVIDER"
VLM_DRAFT_PROMPT_VERSION = "visual_draft.v1"


@dataclass(frozen=True)
class VlmDraftResult:
    text: str = ""
    model: str = ""
    prompt_version: str = VLM_DRAFT_PROMPT_VERSION
    confidence: float | None = None
    provider: str = "none"


class VlmDraftProvider(Protocol):
    name: str

    def available(self) -> bool: ...

    def draft_from_image(self, image_png: bytes, *, page_no: int) -> VlmDraftResult: ...


class NoOpVlmDraftProvider:
    """Default: no VLM. Difficult pages fall through to review_required rather than being invented."""

    name = "none"

    def available(self) -> bool:
        return False

    def draft_from_image(self, image_png: bytes, *, page_no: int) -> VlmDraftResult:
        return VlmDraftResult(provider=self.name)


class CallableVlmDraftProvider:
    """Adapter around a ``callable(image_png, page_no) -> str`` — for injection/tests and thin wiring."""

    name = "callable"

    def __init__(self, fn, *, model: str = "callable", available: bool = True) -> None:
        self._fn = fn
        self._model = model
        self._available = available

    def available(self) -> bool:
        return self._available

    def draft_from_image(self, image_png: bytes, *, page_no: int) -> VlmDraftResult:
        text = (self._fn(image_png, page_no) or "").strip()
        return VlmDraftResult(text=text, model=self._model, provider=self.name)


VLM_DRAFT_PROVIDERS: dict[str, type] = {
    "none": NoOpVlmDraftProvider,
}


def select_vlm_draft_provider(name: str | None = None) -> VlmDraftProvider:
    """Pick a VLM draft provider by name or ``RAKU_VLM_DRAFT_PROVIDER`` env (default: none)."""
    chosen = (name or os.environ.get(VLM_PROVIDER_ENV) or "none").strip().lower()
    factory = VLM_DRAFT_PROVIDERS.get(chosen, NoOpVlmDraftProvider)
    return factory()
