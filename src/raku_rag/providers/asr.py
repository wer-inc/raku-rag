"""T017 — Deterministic ASR provider (022 research.md Decision 2).

MVP contract: the simulator already carries the utterance as text, so ASR "transcribes" by
trusting the text and attaching a confidence (default high; callers/tests can force a low
confidence to exercise the clarification/handoff ladder). Real streaming ASR providers implement
the same `AsrProvider` contract later without changing the orchestrator.
"""

from __future__ import annotations

from raku_rag.phone.interfaces import AsrResult, TelephonyEvent

DEFAULT_CONFIDENCE = 0.95


class DeterministicAsrProvider:
    name = "deterministic-asr"

    def transcribe(self, event: TelephonyEvent) -> AsrResult:
        confidence = (
            float(event.asr_confidence)
            if event.asr_confidence is not None
            else DEFAULT_CONFIDENCE
        )
        confidence = min(1.0, max(0.0, confidence))
        return AsrResult(text=event.text, confidence=confidence, provider=self.name)
