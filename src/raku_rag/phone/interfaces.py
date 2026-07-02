"""T014 — Provider and repository contracts for the phone layer (Constitution IV).

The orchestrator depends only on these Protocols. Deterministic implementations live in
``raku_rag.providers.telephony/asr/tts`` and ``raku_rag.persistence.phone_models``; production
adapters (Amazon Connect / Twilio / SIP, cloud ASR/TTS) plug in behind the same contracts and
stay configuration-gated (plan.md: no live telephony/billed calls without human approval).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from raku_rag.domain.models import IdentityClaims
from raku_rag.phone.domain import CallScenario, CallSession, HandoffPackage


@dataclass(frozen=True)
class TelephonyEvent:
    """Normalized inbound caller event produced by a TelephonyProvider."""

    event_type: str  # speech | dtmf | barge_in | hold | resume | hangup | provider_failure
    text: str = ""
    dtmf_digits: str = ""
    asr_confidence: float | None = None
    barge_in: bool = False
    failed_provider: str = ""  # non-empty when event_type == provider_failure


@dataclass(frozen=True)
class AsrResult:
    """Transcript segment from an AsrProvider."""

    text: str
    confidence: float
    provider: str = "deterministic-asr"


@dataclass(frozen=True)
class TtsResult:
    """TTS-ready response text plus a playable reference from a TtsProvider."""

    text: str
    audio_ref: str
    provider: str = "deterministic-tts"


@dataclass(frozen=True)
class HandoffDispatchResult:
    """Outcome of dispatching a handoff package to a live destination."""

    status: str  # queued | failed | unavailable
    failure_reason: str | None = None


class TelephonyProvider(Protocol):
    """Accepts raw inbound events and normalizes them (FR-001/005/006)."""

    name: str

    def normalize_event(self, raw: dict) -> TelephonyEvent: ...


class AsrProvider(Protocol):
    """Turns caller audio/segments into transcript events (FR-003)."""

    name: str

    def transcribe(self, event: TelephonyEvent) -> AsrResult: ...


class TtsProvider(Protocol):
    """Produces TTS-ready text and a playable audio reference (FR-004)."""

    name: str

    def synthesize(self, tenant_id: str, call_id: str, turn_id: str, text: str) -> TtsResult: ...


class HandoffProvider(Protocol):
    """Dispatches a handoff package toward a queue/department/operator (FR-027/029/030)."""

    name: str

    def dispatch(self, package: HandoffPackage) -> HandoffDispatchResult: ...


class CallRepository(Protocol):
    """Tenant-scoped persistence boundary for calls, turns, and handoff packages."""

    def save_call(self, call: CallSession) -> None: ...

    def get_call(self, tenant_id: str, call_id: str) -> CallSession | None: ...

    def list_calls(self, tenant_id: str) -> list[CallSession]: ...

    def save_handoff(self, package: HandoffPackage) -> None: ...

    def get_handoff(self, tenant_id: str, handoff_package_id: str) -> HandoffPackage | None: ...


class ScenarioRepository(Protocol):
    """Tenant-scoped persistence boundary for scenarios and their versions."""

    def save(self, scenario: CallScenario) -> None: ...

    def get(self, tenant_id: str, scenario_id: str) -> CallScenario | None: ...

    def list(self, tenant_id: str) -> list[CallScenario]: ...


class PhoneAnswerGateway(Protocol):
    """The ONLY path from the phone layer into RAG answering (FR-009).

    Implementations must delegate to the existing tenant-scoped answer service (ACL pre-filter,
    groundedness, citations, manufacturing safety gate) and must never run their own retrieval.
    Returns the manufacturing answer JSON contract: ``{status, text, confidence, citations,
    used_chunks, correlation_id, manufacturing{...}}``.
    """

    def answer(
        self, principal: IdentityClaims, query: str, collection_id: str | None
    ) -> dict: ...


@dataclass
class CallableAnswerGateway:
    """Adapter for the server composition root: wraps the existing rag answer callback."""

    answerer: object
    provider_failures: dict = field(default_factory=dict)

    def answer(self, principal: IdentityClaims, query: str, collection_id: str | None) -> dict:
        return self.answerer(principal, query, collection_id)  # type: ignore[operator]
