"""T019/T043/T046 — Handoff trigger evaluation, package creation, outcome transitions (US2).

Design (research.md Decision 4/5): "人につないで" and the other transfer triggers are HARD rules
evaluated before/around the RAG call — the LLM never decides whether a transfer happens. The
resulting `HandoffPackage` is a first-class entity carrying summary, redacted transcript excerpt,
confirmed slots, citations, sentiment, reason, and destination so the customer never has to
repeat themselves (FR-028).
"""

from __future__ import annotations

from raku_rag.phone.domain import (
    CallSession,
    HandoffPackage,
    PhoneCitationRef,
    new_id,
    now_iso,
)
from raku_rag.phone.interfaces import HandoffDispatchResult, HandoffProvider

# Trigger thresholds (FR-018/026). Deterministic and configuration-overridable at construction.
DEFAULT_LOW_ASR_CONFIDENCE = 0.5
DEFAULT_MAX_LOW_CONFIDENCE_RETRIES = 2
DEFAULT_MAX_CLARIFICATIONS = 3

_HUMAN_REQUEST_TERMS = (
    "人につない",
    "人に繋い",
    "人間",
    "担当者",
    "オペレーター",
    "オペレータ",
    "係の人",
    "human",
    "operator",
    "agent",
)

_HIGH_RISK_TERMS = (
    "返金を確約",
    "返金保証",
    "確約",
    "補償",
    "賠償",
    "損害賠償",
    "訴訟",
    "法的",
    "弁護士",
    "医療",
    "診断",
    "投資助言",
    "契約を保証",
    "セキュリティ事故",
    "情報漏えい",
    "情報漏洩",
    "legal",
    "lawsuit",
    "medical",
)

_NEGATIVE_SENTIMENT_TERMS = (
    "ふざけるな",
    "いい加減にして",
    "いい加減にしろ",
    "許せない",
    "最悪",
    "怒",
    "話にならない",
    "責任者を出せ",
    "クレーム",
    "苦情",
)

# Destination routing by reason/intent (FR-027). Deterministic queue map for the MVP;
# production ACD/skill routing plugs in behind HandoffProvider.
_REASON_PRIORITY = {
    "high_risk_intent": "high",
    "negative_sentiment": "high",
    "provider_failure": "high",
}

_INTENT_QUEUES = {
    "refund_cancellation": "billing-support",
    "pricing_plan": "billing-support",
    "complaint": "escalation",
    "reservation_order_status": "order-support",
}


def detect_human_request(text: str) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in _HUMAN_REQUEST_TERMS)


def detect_high_risk(text: str) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in _HIGH_RISK_TERMS)


def detect_sentiment(text: str) -> str:
    lowered = text.lower()
    if any(term in lowered for term in _NEGATIVE_SENTIMENT_TERMS):
        return "angry"
    return "neutral"


class HandoffRules:
    """Pure trigger evaluation — returns the transfer reason or None, in priority order."""

    def __init__(
        self,
        *,
        low_asr_confidence: float = DEFAULT_LOW_ASR_CONFIDENCE,
        max_low_confidence_retries: int = DEFAULT_MAX_LOW_CONFIDENCE_RETRIES,
        max_clarifications: int = DEFAULT_MAX_CLARIFICATIONS,
    ) -> None:
        self.low_asr_confidence = low_asr_confidence
        self.max_low_confidence_retries = max_low_confidence_retries
        self.max_clarifications = max_clarifications

    def pre_rag_reason(
        self,
        call: CallSession,
        text: str,
        asr_confidence: float | None,
        scenario_reasons: set[str],
    ) -> str | None:
        """Triggers decided before any RAG call. Customer request is unconditional (FR-025)."""
        if detect_human_request(text):
            return "customer_requested_human"
        if detect_high_risk(text) and self._enabled("high_risk_intent", scenario_reasons):
            return "high_risk_intent"
        if detect_sentiment(text) == "angry" and self._enabled(
            "negative_sentiment", scenario_reasons
        ):
            return "negative_sentiment"
        if (
            asr_confidence is not None
            and asr_confidence < self.low_asr_confidence
            and call.low_confidence_count >= self.max_low_confidence_retries
            and self._enabled("low_asr_confidence", scenario_reasons)
        ):
            return "low_asr_confidence"
        if call.clarification_count >= self.max_clarifications and self._enabled(
            "repeated_misunderstanding", scenario_reasons
        ):
            return "repeated_misunderstanding"
        return None

    def _enabled(self, reason: str, scenario_reasons: set[str]) -> bool:
        # An empty scenario set means "no scenario constraints": every safety trigger stays on.
        # customer_requested_human / insufficient_evidence are always on (mandatory defaults).
        if not scenario_reasons:
            return True
        return reason in scenario_reasons


def priority_for(reason: str) -> str:
    return _REASON_PRIORITY.get(reason, "normal")


def destination_for(reason: str, intent: str | None) -> tuple[str, str]:
    if intent and intent in _INTENT_QUEUES:
        return "queue", _INTENT_QUEUES[intent]
    return "queue", "general-support"


class HandoffService:
    """Creates, dispatches, reads, and transitions handoff packages."""

    def __init__(self, provider: HandoffProvider | None = None) -> None:
        self._provider = provider

    def create_package(
        self,
        call: CallSession,
        *,
        reason: str,
        sentiment: str | None = None,
        citations: tuple[PhoneCitationRef, ...] = (),
        recommended_next_action: str | None = None,
    ) -> HandoffPackage:
        destination_type, destination_id = destination_for(reason, call.intent)
        package = HandoffPackage(
            tenant_id=call.tenant_id,
            handoff_package_id=new_id("handoff"),
            call_id=call.call_id,
            reason=reason,
            priority=priority_for(reason),
            destination_type=destination_type,
            destination_id=destination_id,
            caller_phone_number_masked=call.caller_phone_number_masked,
            customer_id=call.customer_id,
            intent=call.intent,
            summary=call.summary,
            transcript_excerpt_redacted=self._transcript_excerpt(call),
            confirmed_slots=dict(call.collected_slots),
            citations=citations,
            sentiment=sentiment,
            recommended_next_action=recommended_next_action
            or self._default_next_action(reason),
        )
        dispatch = self.dispatch(package)
        package.status = dispatch.status
        package.failure_reason = dispatch.failure_reason
        if dispatch.status in {"failed", "unavailable"}:
            # FR-030: live transfer failed -> configured fallback (MVP: callback request).
            package.status = "callback_requested"
        call.handoff_required = True
        call.handoff_reason = reason
        call.handoff_destination = destination_id
        call.handoff_package_id = package.handoff_package_id
        return package

    def dispatch(self, package: HandoffPackage) -> HandoffDispatchResult:
        if self._provider is None:
            return HandoffDispatchResult(status="queued")
        try:
            return self._provider.dispatch(package)
        except Exception:
            return HandoffDispatchResult(status="failed", failure_reason="handoff_provider_error")

    def accept(self, package: HandoffPackage, operator_id: str, queue_id: str | None) -> None:
        package.status = "accepted"
        package.operator_id = operator_id
        package.accepted_at = now_iso()
        if queue_id:
            package.destination_id = queue_id

    def _transcript_excerpt(self, call: CallSession, limit: int = 12) -> str:
        lines: list[str] = []
        for turn in call.turns[-limit:]:
            speaker = {"caller": "顧客", "ai": "AI", "system": "システム", "operator": "担当"}.get(
                turn.speaker, turn.speaker
            )
            text = turn.redacted_text or turn.ai_response_text or ""
            if text:
                lines.append(f"{speaker}: {text}")
        return "\n".join(lines)

    def _default_next_action(self, reason: str) -> str:
        if reason == "insufficient_evidence":
            return "承認済みナレッジの不足箇所を確認し、必要ならナレッジ改善に回してください。"
        if reason == "customer_requested_human":
            return "会話要約と確認済み項目を確認してから応対を引き継いでください。"
        if reason == "high_risk_intent":
            return "高リスク問い合わせです。権限のある担当者へエスカレーションしてください。"
        if reason == "negative_sentiment":
            return "感情状態に配慮した優先応対を行ってください。"
        if reason == "provider_failure":
            return "システム障害転送です。折り返し対応を検討してください。"
        return "会話履歴と転送理由を確認してください。"
