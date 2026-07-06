"""ADR-018 §10 / Phase D — VLM draft fallback for difficult pages (drawings, handwriting, scans).

A VLM is NOT a canonical extractor (§10.1): its output is always ``draft_visual`` — excluded from
retrieval and high-risk citation until a human approves it (Phase A already treats draft_visual as
retrieval-blocking and a review-queue item). This module is the pluggable draft producer; the default
is a NoOp (unavailable), and real Claude/Gemini vision providers are opt-in (API keys, §19 egress
policy). The draft carries crop/bbox + prompt/model version so a reviewer can verify it (§10.2).
"""

from __future__ import annotations

import importlib.util
import os
from dataclasses import dataclass
from typing import Protocol

from raku_rag.providers.ocr.pluggable import cloud_egress_allowed

VLM_PROVIDER_ENV = "RAKU_VLM_DRAFT_PROVIDER"
VLM_DRAFT_PROMPT_VERSION = "visual_draft.v1"

BEDROCK_VLM_MODEL_ENV = "RAKU_BEDROCK_VLM_MODEL_ID"
_DEFAULT_BEDROCK_VLM_MODEL_ID = "jp.anthropic.claude-sonnet-4-5-20250929-v1:0"
_BEDROCK_VLM_PROMPT = (
    "You are a careful OCR transcriber for a manufacturing document. Transcribe ALL legible text in "
    "this page image exactly as printed, preserving line breaks and reading order. Do NOT translate, "
    "summarize, correct, or invent any text; if a region is illegible write [illegible]. Output only "
    "the transcribed text, nothing else."
)


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


class BedrockVlmDraftProvider:
    """Real VLM draft via Amazon Bedrock (Claude vision). Opt-in, §19 cloud-egress-gated.

    Its output is always a DRAFT (``draft_visual``) — never canonical (§10.1) — so a difficult page is
    transcribed for a human to verify, never silently indexed. Stays unavailable unless boto3 is present
    and ``RAKU_ALLOW_CLOUD_EGRESS`` is set, so a misconfiguration cannot exfiltrate document bytes.
    Tests inject ``invoker`` (a ``build_bedrock_vision_invoker``-shaped callable) to validate offline.
    """

    name = "bedrock"

    def __init__(
        self, *, invoker=None, model_id: str | None = None, region: str | None = None
    ) -> None:
        self._invoker = invoker
        self._model_id = (
            model_id or os.environ.get(BEDROCK_VLM_MODEL_ENV) or _DEFAULT_BEDROCK_VLM_MODEL_ID
        )
        self._region = region

    def available(self) -> bool:
        if self._invoker is not None:
            return True
        return cloud_egress_allowed() and importlib.util.find_spec("boto3") is not None

    def _resolve_invoker(self):
        if self._invoker is None:
            from raku_rag.providers.aws_visual import build_bedrock_vision_invoker

            self._invoker = (
                build_bedrock_vision_invoker(region_name=self._region)
                if self._region
                else build_bedrock_vision_invoker()
            )
        return self._invoker

    def draft_from_image(self, image_png: bytes, *, page_no: int) -> VlmDraftResult:
        if not self.available():
            return VlmDraftResult(provider=self.name)
        text = (
            self._resolve_invoker()(
                model_id=self._model_id, prompt=_BEDROCK_VLM_PROMPT, image=image_png
            )
            or ""
        ).strip()
        return VlmDraftResult(text=text, model=self._model_id, provider=self.name)


VLM_DRAFT_PROVIDERS: dict[str, type] = {
    "none": NoOpVlmDraftProvider,
    "bedrock": BedrockVlmDraftProvider,
}


def select_vlm_draft_provider(name: str | None = None) -> VlmDraftProvider:
    """Pick a VLM draft provider by name or ``RAKU_VLM_DRAFT_PROVIDER`` env (default: none)."""
    chosen = (name or os.environ.get(VLM_PROVIDER_ENV) or "none").strip().lower()
    factory = VLM_DRAFT_PROVIDERS.get(chosen, NoOpVlmDraftProvider)
    return factory()
