"""T067 - optional captioning provider boundary."""

from __future__ import annotations

from dataclasses import dataclass

from raku_rag.observability.redaction import Redactor


@dataclass(frozen=True)
class CaptioningResult:
    status: str
    generated_caption_text: str = ""
    failure_reason: str = ""


class DeterministicCaptioningProvider:
    """Fixture captioner.

    Caption output is always redacted and is marked as optional enrichment. Callers must not treat it
    as primary visual evidence (FR-048).
    """

    provider_version = "deterministic-caption-v1"

    def __init__(
        self, *, enabled: bool = True, fail: bool = False, redactor: Redactor | None = None
    ) -> None:
        self.enabled = enabled
        self.fail = fail
        self._redactor = redactor or Redactor()

    def caption(self, image: bytes) -> CaptioningResult:
        if not self.enabled:
            return CaptioningResult(status="not_requested")
        if self.fail:
            return CaptioningResult(status="failed", failure_reason="caption provider unavailable")
        text = image.decode("utf-8", errors="ignore").strip()
        caption = ""
        for line in text.splitlines():
            if line.lower().startswith("caption:"):
                caption = line.split(":", 1)[1].strip()
                break
        if not caption:
            caption = text.splitlines()[0].strip() if text.splitlines() else ""
        return CaptioningResult(
            status="succeeded", generated_caption_text=self._redactor.redact_visual_text(caption)
        )


__all__ = ["CaptioningResult", "DeterministicCaptioningProvider"]
