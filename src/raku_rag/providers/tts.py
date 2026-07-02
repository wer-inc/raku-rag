"""T017/T034 — Deterministic TTS provider (022 research.md Decision 2).

Returns the response text unchanged plus a stable pseudo audio reference
(``deterministic://tts/{call_id}/{turn_id}``) so call history and the operator UI have a
playable-reference contract from day one. Real TTS providers implement the same `TtsProvider`
contract and swap in behind configuration.
"""

from __future__ import annotations

from raku_rag.phone.interfaces import TtsResult


class DeterministicTtsProvider:
    name = "deterministic-tts"

    def synthesize(self, tenant_id: str, call_id: str, turn_id: str, text: str) -> TtsResult:
        return TtsResult(
            text=text,
            audio_ref=f"deterministic://tts/{call_id}/{turn_id}",
            provider=self.name,
        )
