"""T017 — Deterministic telephony provider (022 research.md Decision 1).

The `DeterministicCallSimulator` IS the MVP telephony provider: it normalizes text utterance
events, DTMF, barge-in, and injected provider failures without any network, cloud, or billed
dependency (Tier A constraint). Production adapters (Amazon Connect / Twilio / SIP) implement
the same `TelephonyProvider` contract behind configuration and remain human-gated.
"""

from __future__ import annotations

from raku_rag.phone.interfaces import TelephonyEvent

_EVENT_TYPES = {"speech", "dtmf", "barge_in", "hold", "resume", "hangup", "provider_failure"}


class DeterministicCallSimulator:
    """Normalizes simulated inbound caller events (FR-001/002/005/006)."""

    name = "deterministic-simulator"

    def normalize_event(self, raw: dict) -> TelephonyEvent:
        event_type = str(raw.get("event_type") or raw.get("type") or "speech")
        if event_type not in _EVENT_TYPES:
            event_type = "speech"
        text = str(raw.get("text") or "")
        dtmf = str(raw.get("dtmf_digits") or "")
        if event_type == "speech" and not text and dtmf:
            event_type = "dtmf"
        confidence = raw.get("asr_confidence")
        if raw.get("force_asr_confidence") is not None:
            confidence = raw.get("force_asr_confidence")
        return TelephonyEvent(
            event_type=event_type,
            text=text,
            dtmf_digits=dtmf,
            asr_confidence=float(confidence) if confidence is not None else None,
            barge_in=event_type == "barge_in" or bool(raw.get("barge_in")),
            failed_provider=str(raw.get("failed_provider") or ""),
        )
