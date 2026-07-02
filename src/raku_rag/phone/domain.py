"""T013 — Phone domain models (022-ai-phone-rag data-model.md).

Value/domain models for the AI phone layer. Every entity is tenant-scoped and carries the
trace identifiers required by Constitution II (Traceability): call_id, correlation_id,
scenario_version_id, and citation identifiers. State machines are enforced here so the
orchestrator cannot drive a call or scenario through an illegal transition.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


# --- CallSession state machine (data-model.md §State Machines) ---------------------------------

CALL_STATES = (
    "ringing",
    "active",
    "on_hold",
    "handoff_pending",
    "transferred",
    "completed",
    "abandoned",
    "failed",
)

TERMINAL_CALL_STATES = frozenset({"transferred", "completed", "abandoned", "failed"})

_CALL_TRANSITIONS: dict[str, frozenset[str]] = {
    "ringing": frozenset({"active", "abandoned", "failed"}),
    "active": frozenset({"on_hold", "handoff_pending", "completed", "abandoned", "failed"}),
    "on_hold": frozenset({"active", "handoff_pending", "abandoned", "failed"}),
    "handoff_pending": frozenset({"transferred", "active", "abandoned", "failed"}),
    "transferred": frozenset(),
    "completed": frozenset(),
    "abandoned": frozenset(),
    "failed": frozenset(),
}

AI_ACTIONS = ("ask_clarification", "answer_with_citations", "handoff", "fallback", "end_call")

HANDOFF_STATUSES = (
    "created",
    "queued",
    "accepted",
    "failed",
    "unavailable",
    "abandoned",
    "callback_requested",
)

# Handoff reasons the spec names explicitly (FR-025/026). `customer_requested_human` and
# `insufficient_evidence` are mandatory defaults on every scenario version (data-model invariant).
HANDOFF_REASONS = (
    "customer_requested_human",
    "insufficient_evidence",
    "low_asr_confidence",
    "repeated_misunderstanding",
    "negative_sentiment",
    "high_risk_intent",
    "identity_required",
    "provider_failure",
    "ai_capability_boundary",
)

MANDATORY_HANDOFF_REASONS = ("customer_requested_human", "insufficient_evidence")

SCENARIO_STATUSES = ("draft", "in_review", "approved", "scheduled", "published", "archived")

_SCENARIO_TRANSITIONS: dict[str, frozenset[str]] = {
    "draft": frozenset({"in_review", "archived"}),
    "in_review": frozenset({"approved", "draft", "archived"}),
    "approved": frozenset({"scheduled", "published", "archived"}),
    "scheduled": frozenset({"published", "archived"}),
    "published": frozenset({"archived"}),
    "archived": frozenset(),
}


class InvalidCallTransition(ValueError):
    """Raised when a call would move through an illegal state transition."""


class InvalidScenarioTransition(ValueError):
    """Raised when a scenario version would move through an illegal lifecycle transition."""


def assert_call_transition(current: str, target: str) -> None:
    if target not in _CALL_TRANSITIONS.get(current, frozenset()):
        raise InvalidCallTransition(f"call transition {current} -> {target} is not allowed")


def assert_scenario_transition(current: str, target: str) -> None:
    if target not in _SCENARIO_TRANSITIONS.get(current, frozenset()):
        raise InvalidScenarioTransition(
            f"scenario version transition {current} -> {target} is not allowed"
        )


# --- Value objects ------------------------------------------------------------------------------


@dataclass(frozen=True)
class PhoneCitationRef:
    """Traceable evidence used in a phone turn (Constitution II)."""

    source_id: str
    document_id: str
    chunk_id: str
    version: str | None = None
    retrieval_score: float = 0.0
    approval_status: str | None = None
    effective_date: str | None = None
    snippet_redacted: str | None = None

    def public(self) -> dict:
        return {
            "source_id": self.source_id,
            "document_id": self.document_id,
            "chunk_id": self.chunk_id,
            "version": self.version,
            "retrieval_score": self.retrieval_score,
            "approval_status": self.approval_status,
            "effective_date": self.effective_date,
            "snippet_redacted": self.snippet_redacted,
        }


# --- Entities -----------------------------------------------------------------------------------


@dataclass
class ConversationTurn:
    """One caller/AI/system event in a call. Raw text never leaves this model unredacted:
    ``redacted_text`` is the only display/export surface (data-model invariant)."""

    tenant_id: str
    call_id: str
    turn_id: str
    sequence_no: int
    speaker: str  # caller | ai | system | operator
    event_type: str  # speech | dtmf | barge_in | hold | resume | handoff | tool | error
    asr_text_redacted: str | None = None
    asr_confidence: float | None = None
    dtmf_digits: str | None = None
    redacted_text: str | None = None
    ai_action: str | None = None
    ai_response_text: str | None = None
    tts_audio_ref: str | None = None
    intent: str | None = None
    sentiment: str | None = None
    citations: tuple[PhoneCitationRef, ...] = ()
    safety_decision: dict | None = None
    handoff_reason: str | None = None
    latency_ms: dict = field(default_factory=dict)
    barge_in: bool = False
    created_at: str = field(default_factory=now_iso)

    def public(self) -> dict:
        payload: dict = {
            "turn_id": self.turn_id,
            "sequence_no": self.sequence_no,
            "speaker": self.speaker,
            "event_type": self.event_type,
            "redacted_text": self.redacted_text,
            "created_at": self.created_at,
        }
        if self.speaker == "caller":
            payload["asr_confidence"] = self.asr_confidence
            if self.dtmf_digits:
                payload["dtmf_digits"] = self.dtmf_digits
            if self.barge_in:
                payload["barge_in"] = True
        if self.speaker == "ai":
            payload.update(
                {
                    "ai_action": self.ai_action,
                    "tts_audio_ref": self.tts_audio_ref,
                    "citations": [c.public() for c in self.citations],
                    "latency_ms": dict(self.latency_ms),
                }
            )
            if self.safety_decision is not None:
                payload["safety"] = dict(self.safety_decision)
            if self.handoff_reason:
                payload["handoff_reason"] = self.handoff_reason
        return payload


@dataclass
class CallSession:
    """One inbound or simulated phone call (data-model.md §CallSession)."""

    tenant_id: str
    call_id: str
    correlation_id: str
    channel: str = "simulator"
    provider: str = "deterministic-simulator"
    provider_call_id: str | None = None
    caller_phone_number_masked: str | None = None
    customer_id: str | None = None
    started_at: str = field(default_factory=now_iso)
    answered_at: str | None = None
    ended_at: str | None = None
    state: str = "ringing"
    intent: str | None = None
    scenario_id: str | None = None
    scenario_version_id: str | None = None
    scenario_path: list[str] = field(default_factory=list)
    summary: str = ""
    resolution_status: str | None = None
    handoff_required: bool = False
    handoff_reason: str | None = None
    handoff_destination: str | None = None
    handoff_package_id: str | None = None
    recording_enabled: bool = False
    recording_disclosure_played: bool = False
    audio_object_ref: str | None = None
    transcript_redaction_status: str = "not_needed"
    turns: list[ConversationTurn] = field(default_factory=list)
    clarification_count: int = 0
    low_confidence_count: int = 0
    collected_slots: dict[str, str] = field(default_factory=dict)
    missing_slots: list[str] = field(default_factory=list)
    awaiting_slot: str | None = None
    pending_query: str | None = None
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)

    def transition(self, target: str) -> None:
        assert_call_transition(self.state, target)
        self.state = target
        self.updated_at = now_iso()
        if target in TERMINAL_CALL_STATES:
            self.ended_at = self.updated_at
            if self.resolution_status is None:
                self.resolution_status = {
                    "transferred": "transferred",
                    "completed": "resolved",
                    "abandoned": "abandoned",
                    "failed": "failed",
                }[target]

    def is_terminal(self) -> bool:
        return self.state in TERMINAL_CALL_STATES

    def next_sequence_no(self) -> int:
        return len(self.turns) + 1

    def summary_item(self) -> dict:
        return {
            "call_id": self.call_id,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "caller_phone_number_masked": self.caller_phone_number_masked,
            "customer_id": self.customer_id,
            "intent": self.intent,
            "state": self.state,
            "resolution_status": self.resolution_status,
            "handoff_required": self.handoff_required,
            "handoff_reason": self.handoff_reason,
            "scenario_id": self.scenario_id,
            "scenario_version_id": self.scenario_version_id,
        }


@dataclass
class ScenarioVersion:
    """Immutable-once-published version of a call scenario (FR-021/022)."""

    tenant_id: str
    scenario_id: str
    scenario_version_id: str
    version_number: int
    status: str = "draft"
    entry_conditions: list[dict] = field(default_factory=list)
    steps: list[dict] = field(default_factory=list)
    required_slots: list[dict] = field(default_factory=list)
    branch_conditions: list[dict] = field(default_factory=list)
    allowed_actions: list[str] = field(default_factory=list)
    handoff_conditions: list[dict] = field(default_factory=list)
    fallback_message: str = "確認して担当者におつなぎします。"
    response_templates: list[dict] = field(default_factory=list)
    approved_by: str | None = None
    approved_at: str | None = None
    published_by: str | None = None
    published_at: str | None = None
    scheduled_publish_at: str | None = None
    archived_by: str | None = None
    archived_at: str | None = None
    supersedes_version_id: str | None = None
    rollback_target_version_id: str | None = None
    created_by: str = ""
    created_at: str = field(default_factory=now_iso)

    def is_immutable(self) -> bool:
        return self.status in {"published", "archived"}

    def public(self) -> dict:
        return {
            "scenario_version_id": self.scenario_version_id,
            "version_number": self.version_number,
            "status": self.status,
            "entry_conditions": [dict(c) for c in self.entry_conditions],
            "steps": [dict(s) for s in self.steps],
            "required_slots": [dict(s) for s in self.required_slots],
            "branch_conditions": [dict(c) for c in self.branch_conditions],
            "allowed_actions": list(self.allowed_actions),
            "handoff_conditions": [dict(c) for c in self.handoff_conditions],
            "fallback_message": self.fallback_message,
            "response_templates": [dict(t) for t in self.response_templates],
            "approved_by": self.approved_by,
            "approved_at": self.approved_at,
            "published_by": self.published_by,
            "published_at": self.published_at,
            "scheduled_publish_at": self.scheduled_publish_at,
            "supersedes_version_id": self.supersedes_version_id,
            "rollback_target_version_id": self.rollback_target_version_id,
            "created_by": self.created_by,
            "created_at": self.created_at,
        }


@dataclass
class CallScenario:
    """Logical scenario record edited by admins; versions carry the actual payload."""

    tenant_id: str
    scenario_id: str
    name: str
    intent: str
    description: str | None = None
    status: str = "draft"
    active_version_id: str | None = None
    owner_group: str | None = None
    created_by: str = ""
    versions: dict[str, ScenarioVersion] = field(default_factory=dict)
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)

    def version(self, version_id: str) -> ScenarioVersion | None:
        return self.versions.get(version_id)

    def active_version(self) -> ScenarioVersion | None:
        if not self.active_version_id:
            return None
        return self.versions.get(self.active_version_id)

    def next_version_number(self) -> int:
        return max((v.version_number for v in self.versions.values()), default=0) + 1

    def public(self) -> dict:
        return {
            "scenario_id": self.scenario_id,
            "name": self.name,
            "intent": self.intent,
            "description": self.description,
            "status": self.status,
            "active_version_id": self.active_version_id,
            "owner_group": self.owner_group,
            "versions": [v.public() for v in self.versions.values()],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class HandoffPackage:
    """Context passed to a human operator (FR-028). Never carries raw caller PII."""

    tenant_id: str
    handoff_package_id: str
    call_id: str
    reason: str
    destination_type: str = "queue"
    destination_id: str = "general-support"
    status: str = "created"
    priority: str = "normal"
    caller_phone_number_masked: str | None = None
    customer_id: str | None = None
    intent: str | None = None
    summary: str = ""
    transcript_excerpt_redacted: str = ""
    confirmed_slots: dict[str, str] = field(default_factory=dict)
    citations: tuple[PhoneCitationRef, ...] = ()
    sentiment: str | None = None
    recommended_next_action: str | None = None
    operator_id: str | None = None
    accepted_at: str | None = None
    failure_reason: str | None = None
    created_at: str = field(default_factory=now_iso)

    def public(self) -> dict:
        return {
            "handoff_package_id": self.handoff_package_id,
            "call_id": self.call_id,
            "status": self.status,
            "reason": self.reason,
            "priority": self.priority,
            "destination_type": self.destination_type,
            "destination_id": self.destination_id,
            "customer": {
                "customer_id": self.customer_id,
                "phone_number_masked": self.caller_phone_number_masked,
            },
            "intent": self.intent,
            "summary": self.summary,
            "transcript_excerpt_redacted": self.transcript_excerpt_redacted,
            "confirmed_slots": dict(self.confirmed_slots),
            "citations": [c.public() for c in self.citations],
            "sentiment": self.sentiment,
            "recommended_next_action": self.recommended_next_action,
            "operator_id": self.operator_id,
            "accepted_at": self.accepted_at,
            "failure_reason": self.failure_reason,
            "created_at": self.created_at,
        }


@dataclass
class QualityEvaluation:
    """Supervisor review of a call (US4 — persisted shape defined now, workflow lands later)."""

    tenant_id: str
    evaluation_id: str
    call_id: str
    reviewer_id: str
    reviewed_at: str = field(default_factory=now_iso)
    answer_correctness: int | None = None
    tone_score: int | None = None
    handoff_appropriateness: int | None = None
    compliance_issue: bool = False
    hallucination_detected: bool = False
    privacy_issue: bool = False
    suggested_fix: str | None = None
    knowledge_gap_topics: list[str] = field(default_factory=list)
    review_status: str = "open"
    improvement_item_id: str | None = None


@dataclass
class ProviderConfig:
    """Tenant/runtime provider selection. ``deterministic`` must stay offline (plan constraint)."""

    tenant_id: str
    config_id: str
    runtime_profile: str = "deterministic"
    telephony_provider: str = "deterministic-simulator"
    asr_provider: str = "deterministic-asr"
    tts_provider: str = "deterministic-tts"
    handoff_provider: str = "in-memory-queue"
    allowed_intents: list[str] = field(default_factory=list)
    blocked_intents: list[str] = field(default_factory=list)
