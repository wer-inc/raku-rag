"""T020/T030/T031/T033/T044/T057 — Phone conversation orchestrator (US1/US2/US3).

Design (research.md Decision 4): the orchestrator decides one of
``ask_clarification | answer_with_citations | handoff | fallback | end_call`` per turn. RAG text
generation happens inside the `answer_with_citations` branch through `PhoneAnswerGateway`
(the existing tenant-scoped AnswerService + manufacturing safety gate — FR-009); the state
transition itself is decided by hard policy/scenario/safety rules, never by the LLM.
"""

from __future__ import annotations

import re
import time

from raku_rag.domain.models import IdentityClaims
from raku_rag.phone.domain import (
    CallSession,
    ConversationTurn,
    PhoneCitationRef,
    ScenarioVersion,
    new_id,
)
from raku_rag.phone.handoff import HandoffRules, HandoffService, detect_sentiment
from raku_rag.phone.interfaces import (
    AsrProvider,
    CallRepository,
    PhoneAnswerGateway,
    TelephonyEvent,
    TelephonyProvider,
    TtsProvider,
)
from raku_rag.phone.redaction import mask_phone_number, redact_text
from raku_rag.phone.scenarios import PhoneScenarioService, ScenarioError

SIMULATE_ROLES = frozenset({"tenant_admin", "ops_owner", "qa_reviewer"})
CALL_READ_ROLES = frozenset({"ops_owner", "tenant_admin", "qa_reviewer"})
HANDOFF_READ_ROLES = frozenset({"operator", "ops_owner", "tenant_admin"})

# Citations whose approval metadata marks them not currently usable never ground a spoken answer
# (spec edge case: 古い版・停止中・承認待ち・権限外のみ → 正式回答に使わない).
_BLOCKED_APPROVAL_STATUSES = {"draft", "pending_review", "obsolete", "rejected"}

_MIN_ANSWER_CONFIDENCE = 0.2

_LOW_CONFIDENCE_PROMPT = "恐れ入ります、うまく聞き取れませんでした。もう一度お願いできますか。"
_HANDOFF_NOTICE = "担当者におつなぎします。ここまでの内容を引き継ぎます。"
_INSUFFICIENT_NOTICE = "承認済みの情報だけでは確認できませんでした。担当者におつなぎします。"
_HOLD_NOTICE = "少々お待ちください。確認いたします。"
_RESUME_NOTICE = "お待たせしました。"
_RECORDING_DISCLOSURE = "品質向上のため、この通話は記録される場合があります。"

_INTENT_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("human_handoff", ("人につない", "人に繋い", "担当者", "オペレーター", "オペレータ")),
    ("business_hours", ("営業時間", "何時まで", "何時から", "営業日", "定休日")),
    ("refund_cancellation", ("返金", "解約", "キャンセル", "退会")),
    ("pricing_plan", ("料金", "価格", "費用", "プラン", "値段", "お見積")),
    ("reservation_order_status", ("予約", "注文", "配送", "納期", "ステータス", "進捗", "状況")),
    ("document_request", ("資料", "カタログ", "パンフレット", "書類", "送ってください", "送付")),
    ("complaint", ("クレーム", "苦情", "不満")),
    ("department_routing", ("部署", "営業部", "総務", "経理", "窓口", "担当部門")),
)


def classify_intent(text: str, current: str | None) -> str:
    lowered = text.lower()
    for intent, keywords in _INTENT_KEYWORDS:
        if any(k in lowered for k in keywords):
            return intent
    return current or "faq"


class PhoneCallService:
    """Owns call sessions, turn execution, handoff reads, and scenario preview execution."""

    def __init__(
        self,
        answer_gateway: PhoneAnswerGateway,
        *,
        repository: CallRepository,
        scenarios: PhoneScenarioService,
        telephony: TelephonyProvider,
        asr: AsrProvider,
        tts: TtsProvider,
        handoff: HandoffService | None = None,
        rules: HandoffRules | None = None,
    ) -> None:
        self._gateway = answer_gateway
        self._repo = repository
        self._scenarios = scenarios
        self._telephony = telephony
        self._asr = asr
        self._tts = tts
        self._handoff = handoff or HandoffService()
        self._rules = rules or HandoffRules()

    # --- public API (internal HTTP surface) ----------------------------------------------------

    def simulate_call(self, principal: IdentityClaims, body: dict) -> tuple[int, dict]:
        if not self._has_any_role(principal, SIMULATE_ROLES):
            return 403, {"error": "forbidden"}
        caller = dict(body.get("caller") or {})
        scenario_id = str(body.get("scenario_id") or "") or None
        version = self._scenarios.resolve_for_call(principal.tenant_id, scenario_id)
        options = dict(body.get("options") or {})
        call = CallSession(
            tenant_id=principal.tenant_id,
            call_id=new_id("call"),
            correlation_id=new_id("corr"),
            channel=str(body.get("channel") or "simulator"),
            provider=self._telephony.name,
            caller_phone_number_masked=mask_phone_number(str(caller.get("phone_number") or "")),
            customer_id=str(caller.get("customer_id") or "") or None,
            scenario_id=scenario_id,
            scenario_version_id=version.scenario_version_id if version else None,
            recording_enabled=bool(options.get("recording_enabled", False)),
        )
        call.transition("active")
        call.answered_at = call.updated_at
        if call.recording_enabled:
            # FR-042: disclosure prompt is played (and recorded as played) before conversation.
            call.recording_disclosure_played = True
            self._system_turn(call, _RECORDING_DISCLOSURE)
        if version and version.required_slots:
            call.missing_slots = [str(s.get("slot") or "") for s in version.required_slots]
        self._repo.save_call(call)

        turns: list[dict] = []
        for raw in body.get("utterances") or []:
            raw = dict(raw)
            if options.get("force_asr_confidence") is not None and "asr_confidence" not in raw:
                raw["asr_confidence"] = options.get("force_asr_confidence")
            status, payload = self._execute_turn(
                principal, call, raw, collection_id=body.get("collection_id")
            )
            turns.append(payload)
            if status != 200 or call.is_terminal():
                break
        self._repo.save_call(call)
        return 202, {
            **self._envelope(principal, call.correlation_id),
            "call_id": call.call_id,
            "status": call.state,
            "status_url": f"/v1/phone/calls/{call.call_id}",
            "turns": turns,
        }

    def submit_turn(self, principal: IdentityClaims, call_id: str, body: dict) -> tuple[int, dict]:
        if not self._has_any_role(principal, SIMULATE_ROLES):
            return 403, {"error": "forbidden"}
        call = self._repo.get_call(principal.tenant_id, call_id)
        if not call:
            return 404, {"error": "not_found"}
        if call.is_terminal():
            return 409, {"error": "call_terminal"}
        status, payload = self._execute_turn(
            principal, call, dict(body), collection_id=body.get("collection_id")
        )
        self._repo.save_call(call)
        return status, payload

    def get_call(self, principal: IdentityClaims, call_id: str) -> tuple[int, dict]:
        call = self._repo.get_call(principal.tenant_id, call_id)
        if not call or not self._can_read_call(principal):
            return 404 if not call else 403, {"error": "not_found" if not call else "forbidden"}
        handoff = (
            self._repo.get_handoff(principal.tenant_id, call.handoff_package_id)
            if call.handoff_package_id
            else None
        )
        return 200, {
            **self._envelope(principal, call.correlation_id),
            "call_id": call.call_id,
            "state": call.state,
            "started_at": call.started_at,
            "ended_at": call.ended_at,
            "caller_phone_number_masked": call.caller_phone_number_masked,
            "customer_id": call.customer_id,
            "intent": call.intent,
            "summary": call.summary,
            "resolution_status": call.resolution_status,
            "scenario_id": call.scenario_id,
            "scenario_version_id": call.scenario_version_id,
            "recording_enabled": call.recording_enabled,
            "recording_disclosure_played": call.recording_disclosure_played,
            "transcript_redaction_status": call.transcript_redaction_status,
            "transcript": [t.public() for t in call.turns],
            "handoff": handoff.public() if handoff else None,
        }

    def list_calls(self, principal: IdentityClaims, query: dict | None = None) -> tuple[int, dict]:
        if not self._can_read_call(principal):
            return 403, {"error": "forbidden"}
        query = query or {}

        def _q(name: str) -> str:
            value = query.get(name)
            if isinstance(value, list):
                return str(value[0]) if value else ""
            return str(value or "")

        items = []
        for call in self._repo.list_calls(principal.tenant_id):
            if _q("intent") and call.intent != _q("intent"):
                continue
            if _q("state") and call.state != _q("state"):
                continue
            if _q("handoff_reason") and call.handoff_reason != _q("handoff_reason"):
                continue
            if _q("scenario_id") and call.scenario_id != _q("scenario_id"):
                continue
            if _q("customer_id") and call.customer_id != _q("customer_id"):
                continue
            items.append(call.summary_item())
        items.sort(key=lambda item: item["started_at"], reverse=True)
        return 200, {
            **self._envelope(principal, new_id("corr")),
            "items": items,
            "next_cursor": None,
        }

    def get_handoff(self, principal: IdentityClaims, handoff_package_id: str) -> tuple[int, dict]:
        if not self._has_any_role(principal, HANDOFF_READ_ROLES):
            return 403, {"error": "forbidden"}
        package = self._repo.get_handoff(principal.tenant_id, handoff_package_id)
        if not package:
            return 404, {"error": "not_found"}
        return 200, {**self._envelope(principal, new_id("corr")), **package.public()}

    def accept_handoff(
        self, principal: IdentityClaims, handoff_package_id: str, body: dict
    ) -> tuple[int, dict]:
        if not self._has_any_role(principal, HANDOFF_READ_ROLES):
            return 403, {"error": "forbidden"}
        package = self._repo.get_handoff(principal.tenant_id, handoff_package_id)
        if not package:
            return 404, {"error": "not_found"}
        self._handoff.accept(
            package,
            operator_id=str(body.get("operator_id") or principal.user_id),
            queue_id=str(body.get("queue_id") or "") or None,
        )
        self._repo.save_handoff(package)
        call = self._repo.get_call(principal.tenant_id, package.call_id)
        if call and call.state == "handoff_pending":
            call.transition("transferred")
            self._repo.save_call(call)
        return 200, {
            **self._envelope(principal, new_id("corr")),
            "handoff_package_id": package.handoff_package_id,
            "status": package.status,
            "accepted_at": package.accepted_at,
        }

    # --- scenario HTTP surface (delegates lifecycle to PhoneScenarioService) --------------------

    def list_scenarios(self, principal: IdentityClaims) -> tuple[int, dict]:
        if not self._scenarios.can_read(principal):
            return 403, {"error": "forbidden"}
        return 200, {
            **self._envelope(principal, new_id("corr")),
            "items": self._scenarios.list(principal),
        }

    def create_scenario(self, principal: IdentityClaims, body: dict) -> tuple[int, dict]:
        if not self._scenarios.can_manage(principal):
            return 403, {"error": "forbidden"}
        try:
            scenario = self._scenarios.create(principal, body)
        except ScenarioError as exc:
            return exc.status, {"error": exc.code}
        return 201, {
            **self._envelope(principal, new_id("corr")),
            "scenario_id": scenario.scenario_id,
            "status": scenario.status,
            "active_version_id": scenario.active_version_id,
            "versions": [v.public() for v in scenario.versions.values()],
        }

    def upsert_scenario_version(
        self, principal: IdentityClaims, scenario_id: str, version_id: str, body: dict
    ) -> tuple[int, dict]:
        if not self._scenarios.can_manage(principal):
            return 403, {"error": "forbidden"}
        try:
            version = self._scenarios.upsert_version(principal, scenario_id, version_id, body)
        except ScenarioError as exc:
            return exc.status, {"error": exc.code}
        return 200, {
            **self._envelope(principal, new_id("corr")),
            "scenario_id": scenario_id,
            "scenario_version_id": version.scenario_version_id,
            "status": version.status,
        }

    def scenario_action(
        self, principal: IdentityClaims, scenario_id: str, version_id: str, action: str, body: dict
    ) -> tuple[int, dict]:
        if action == "test":
            return self.preview_scenario(principal, scenario_id, version_id, body)
        if action in {"approve", "publish", "schedule", "archive"}:
            if not self._scenarios.can_approve(principal):
                return 403, {"error": "forbidden"}
        elif not self._scenarios.can_manage(principal):
            return 403, {"error": "forbidden"}
        try:
            scenario, version = self._scenarios.action(
                principal, scenario_id, version_id, action, body
            )
        except ScenarioError as exc:
            return exc.status, {"error": exc.code}
        payload = {
            **self._envelope(principal, new_id("corr")),
            "scenario_id": scenario.scenario_id,
            "scenario_version_id": version.scenario_version_id,
            "status": version.status,
        }
        if action == "publish":
            payload["active_version_id"] = scenario.active_version_id
        if action == "schedule":
            payload["scheduled_publish_at"] = version.scheduled_publish_at
        return 200, payload

    def rollback_scenario(
        self, principal: IdentityClaims, scenario_id: str, body: dict
    ) -> tuple[int, dict]:
        if not self._scenarios.can_approve(principal):
            return 403, {"error": "forbidden"}
        try:
            scenario, version = self._scenarios.rollback(principal, scenario_id, body)
        except ScenarioError as exc:
            return exc.status, {"error": exc.code}
        return 200, {
            **self._envelope(principal, new_id("corr")),
            "scenario_id": scenario.scenario_id,
            "active_version_id": scenario.active_version_id,
            "rollback_target_version_id": version.rollback_target_version_id,
            "status": scenario.status,
        }

    def preview_scenario(
        self,
        principal: IdentityClaims,
        scenario_id: str,
        version_id: str,
        body: dict,
    ) -> tuple[int, dict]:
        """T057 — run a NON-persisted preview conversation against a specific (draft) version."""
        if not self._scenarios.can_manage(principal) and not self._scenarios.can_approve(principal):
            return 403, {"error": "forbidden"}
        scenario = self._scenarios._repo.get(principal.tenant_id, scenario_id)  # noqa: SLF001
        version = scenario.version(version_id) if scenario else None
        if not scenario or not version:
            return 404, {"error": "not_found"}
        call = CallSession(
            tenant_id=principal.tenant_id,
            call_id=new_id("preview"),
            correlation_id=new_id("corr"),
            channel="simulator",
            scenario_id=scenario_id,
            scenario_version_id=version_id,
        )
        call.transition("active")
        if version.required_slots:
            call.missing_slots = [str(s.get("slot") or "") for s in version.required_slots]
        turns: list[dict] = []
        would_handoff = False
        for utterance in body.get("utterances") or []:
            raw = utterance if isinstance(utterance, dict) else {"type": "speech", "text": str(utterance)}
            if call.is_terminal():
                break
            _, payload = self._execute_turn(
                principal, call, dict(raw), collection_id=body.get("collection_id"),
                scenario_version=version, persist_handoff=False,
            )
            turns.append(
                {
                    "ai_action": payload.get("ai_action"),
                    "ai_response_text": payload.get("ai_response_text"),
                    "citations": payload.get("citations") or [],
                }
            )
            if payload.get("ai_action") == "handoff":
                would_handoff = True
        return 200, {
            **self._envelope(principal, call.correlation_id),
            "scenario_id": scenario_id,
            "scenario_version_id": version_id,
            "turns": turns,
            "would_handoff": would_handoff,
        }

    # --- turn execution --------------------------------------------------------------------------

    def _execute_turn(
        self,
        principal: IdentityClaims,
        call: CallSession,
        raw: dict,
        *,
        collection_id: str | None,
        scenario_version: ScenarioVersion | None = None,
        persist_handoff: bool = True,
    ) -> tuple[int, dict]:
        started = time.perf_counter()
        event = self._telephony.normalize_event(raw)
        version = scenario_version or self._scenarios.resolve_for_call(
            call.tenant_id, call.scenario_id
        )
        scenario_reasons = self._enabled_reasons(version)

        if event.event_type == "provider_failure":
            return self._handle_provider_failure(
                principal, call, event, version, persist_handoff=persist_handoff
            )
        if event.event_type == "hangup":
            call.transition("completed" if self._has_answer(call) else "abandoned")
            turn = self._ai_turn(call, "end_call", "お電話ありがとうございました。", started)
            return 200, self._turn_payload(principal, call, turn, handoff=None)
        if event.event_type == "hold":
            call.transition("on_hold")
            turn = self._ai_turn(call, "fallback", _HOLD_NOTICE, started)
            return 200, self._turn_payload(principal, call, turn, handoff=None)
        if event.event_type == "resume":
            call.transition("active")
            turn = self._ai_turn(call, "fallback", _RESUME_NOTICE, started)
            return 200, self._turn_payload(principal, call, turn, handoff=None)

        asr_started = time.perf_counter()
        asr = self._asr.transcribe(event)
        asr_ms = (time.perf_counter() - asr_started) * 1000
        caller_turn = self._caller_turn(call, event, asr)

        # FR-005: barge-in stops AI speech; caller input wins. Deterministically recorded on the
        # caller turn; the interrupted AI turn is the previous one in the transcript.
        text = asr.text.strip()
        sentiment = detect_sentiment(text)
        caller_turn.sentiment = sentiment

        if text:
            intent = classify_intent(text, call.intent)
            caller_turn.intent = intent
            if intent != "human_handoff":
                call.intent = intent

        # Low ASR confidence -> bounded re-ask, then transfer (FR-018/026).
        if event.event_type != "dtmf" and asr.confidence < self._rules.low_asr_confidence:
            call.low_confidence_count += 1
            reason = self._rules.pre_rag_reason(call, text, asr.confidence, scenario_reasons)
            if reason:
                return self._handoff_turn(
                    principal, call, reason, sentiment, started, version,
                    persist_handoff=persist_handoff,
                )
            call.clarification_count += 1
            turn = self._ai_turn(call, "ask_clarification", _LOW_CONFIDENCE_PROMPT, started,
                                 asr_ms=asr_ms)
            return 200, self._turn_payload(principal, call, turn, handoff=None)

        reason = self._rules.pre_rag_reason(call, text, asr.confidence, scenario_reasons)
        if reason:
            return self._handoff_turn(
                principal, call, reason, sentiment, started, version,
                persist_handoff=persist_handoff,
            )

        # Scenario slot collection (FR-014): the question is parked, the awaited slot is filled
        # from the NEXT utterance/DTMF, then the parked question runs against RAG.
        if call.missing_slots:
            if call.awaiting_slot:
                value = event.dtmf_digits or self._slot_value(text)
                if value:
                    call.collected_slots[call.awaiting_slot] = redact_text(value).text
                    call.missing_slots = [
                        s for s in call.missing_slots if s != call.awaiting_slot
                    ]
                    call.awaiting_slot = None
                if call.missing_slots:
                    call.awaiting_slot = call.missing_slots[0]
                    prompt = self._slot_prompt(version, call.awaiting_slot)
                    turn = self._ai_turn(call, "ask_clarification", prompt, started, asr_ms=asr_ms)
                    return 200, self._turn_payload(principal, call, turn, handoff=None)
                # All required slots collected: answer the parked question.
                if call.pending_query:
                    text = call.pending_query
                    call.pending_query = None
            else:
                call.pending_query = text or call.pending_query
                call.awaiting_slot = call.missing_slots[0]
                prompt = self._slot_prompt(version, call.awaiting_slot)
                turn = self._ai_turn(call, "ask_clarification", prompt, started, asr_ms=asr_ms)
                return 200, self._turn_payload(principal, call, turn, handoff=None)

        if event.event_type == "dtmf":
            turn = self._ai_turn(
                call, "ask_clarification", "番号を受け付けました。ご用件をお話しください。",
                started, asr_ms=asr_ms,
            )
            return 200, self._turn_payload(principal, call, turn, handoff=None)

        return self._rag_turn(
            principal, call, text, collection_id, started, asr_ms, version,
            sentiment=sentiment, persist_handoff=persist_handoff,
        )

    def _rag_turn(
        self,
        principal: IdentityClaims,
        call: CallSession,
        text: str,
        collection_id: str | None,
        started: float,
        asr_ms: float,
        version: ScenarioVersion | None,
        *,
        sentiment: str,
        persist_handoff: bool,
    ) -> tuple[int, dict]:
        rag_started = time.perf_counter()
        try:
            response = self._gateway.answer(principal, text, collection_id)
        except Exception:
            # Fail closed (FR-045): a broken RAG path never produces an unsupported answer.
            return self._handoff_turn(
                principal, call, "provider_failure", sentiment, started, version,
                persist_handoff=persist_handoff,
            )
        rag_ms = (time.perf_counter() - rag_started) * 1000

        status = str(response.get("status") or "temporarily_unavailable")
        citations, dropped_blocked = self._phone_citations(response.get("citations") or [])
        manufacturing = dict(response.get("manufacturing") or {})
        confidence = response.get("confidence")
        answerable = (
            status == "ok"
            and bool(citations)
            and bool(response.get("text"))
            and (confidence is None or float(confidence) >= _MIN_ANSWER_CONFIDENCE)
        )
        blocked_reason = None
        if not answerable:
            blocked_reason = (
                "stale_or_unapproved_evidence"
                if status == "ok" and dropped_blocked and not citations
                else manufacturing.get("safety_block_reason") or status
            )

        if answerable:
            speech = str(response.get("text") or "").strip()
            notice = str(manufacturing.get("notice") or "")
            if notice:
                speech = f"{speech}\n{notice}"
            turn = self._ai_turn(
                call,
                "answer_with_citations",
                speech,
                started,
                asr_ms=asr_ms,
                rag_ms=rag_ms,
                citations=citations,
                safety={
                    "answered_with_evidence": True,
                    "blocked_reason": None,
                    "high_risk": bool(manufacturing.get("high_risk")),
                },
                trace_id=str(response.get("correlation_id") or ""),
            )
            return 200, self._turn_payload(principal, call, turn, handoff=None)

        # Insufficient / blocked evidence -> never assert; transfer with context (FR-010/012).
        return self._handoff_turn(
            principal, call, "insufficient_evidence", sentiment, started, version,
            blocked_reason=str(blocked_reason or "insufficient_evidence"),
            persist_handoff=persist_handoff,
        )

    def _handle_provider_failure(
        self,
        principal: IdentityClaims,
        call: CallSession,
        event: TelephonyEvent,
        version: ScenarioVersion | None,
        *,
        persist_handoff: bool,
    ) -> tuple[int, dict]:
        started = time.perf_counter()
        failed = event.failed_provider or "telephony"
        if failed in {"asr", "tts"}:
            # Degraded but recoverable: play the scenario fallback and continue (FR-030, SC-008).
            message = version.fallback_message if version else "確認して担当者におつなぎします。"
            turn = self._ai_turn(call, "fallback", message, started)
            return 200, self._turn_payload(principal, call, turn, handoff=None)
        # LLM/RAG/handoff/telephony failures fail closed into a human path.
        return self._handoff_turn(
            principal, call, "provider_failure", "unknown", started, version,
            persist_handoff=persist_handoff,
        )

    def _handoff_turn(
        self,
        principal: IdentityClaims,
        call: CallSession,
        reason: str,
        sentiment: str,
        started: float,
        version: ScenarioVersion | None,
        *,
        blocked_reason: str | None = None,
        persist_handoff: bool = True,
    ) -> tuple[int, dict]:
        existing = (
            self._repo.get_handoff(call.tenant_id, call.handoff_package_id)
            if call.handoff_package_id
            else None
        )
        if existing:
            package = existing
        else:
            citations = self._last_answer_citations(call)
            package = self._handoff.create_package(
                call, reason=reason, sentiment=sentiment, citations=citations
            )
            if persist_handoff:
                self._repo.save_handoff(package)
        if call.state in {"active", "on_hold", "ringing"}:
            if call.state == "ringing":
                call.transition("active")
            call.transition("handoff_pending")
        message = _INSUFFICIENT_NOTICE if reason == "insufficient_evidence" else _HANDOFF_NOTICE
        if version and reason == "insufficient_evidence" and version.fallback_message:
            message = version.fallback_message
        turn = self._ai_turn(
            call,
            "handoff",
            message,
            started,
            citations=(),
            safety={
                "answered_with_evidence": False,
                "blocked_reason": blocked_reason if blocked_reason else (
                    reason if reason == "insufficient_evidence" else None
                ),
            },
            handoff_reason=reason,
        )
        return 200, self._turn_payload(principal, call, turn, handoff=package)

    # --- turn/record helpers ----------------------------------------------------------------------

    def _caller_turn(self, call: CallSession, event: TelephonyEvent, asr) -> ConversationTurn:
        redaction = redact_text(asr.text)
        if redaction.flagged:
            call.transcript_redaction_status = "redacted"
        turn = ConversationTurn(
            tenant_id=call.tenant_id,
            call_id=call.call_id,
            turn_id=f"turn_{call.next_sequence_no():03d}",
            sequence_no=call.next_sequence_no(),
            speaker="caller",
            event_type=event.event_type,
            asr_text_redacted=redaction.text,
            asr_confidence=asr.confidence,
            dtmf_digits=event.dtmf_digits or None,
            redacted_text=redaction.text,
            barge_in=event.barge_in,
        )
        call.turns.append(turn)
        self._update_summary(call)
        return turn

    def _ai_turn(
        self,
        call: CallSession,
        action: str,
        text: str,
        started: float,
        *,
        asr_ms: float = 0.0,
        rag_ms: float = 0.0,
        citations: tuple[PhoneCitationRef, ...] = (),
        safety: dict | None = None,
        handoff_reason: str | None = None,
        trace_id: str = "",
    ) -> ConversationTurn:
        turn_id = f"turn_{call.next_sequence_no():03d}"
        tts_started = time.perf_counter()
        tts = self._tts.synthesize(call.tenant_id, call.call_id, turn_id, text)
        tts_ms = (time.perf_counter() - tts_started) * 1000
        redaction = redact_text(text)
        turn = ConversationTurn(
            tenant_id=call.tenant_id,
            call_id=call.call_id,
            turn_id=turn_id,
            sequence_no=call.next_sequence_no(),
            speaker="ai",
            event_type="speech",
            redacted_text=redaction.text,
            ai_action=action,
            ai_response_text=redaction.text,
            tts_audio_ref=tts.audio_ref,
            intent=call.intent,
            citations=citations,
            safety_decision=dict(safety) if safety else None,
            handoff_reason=handoff_reason,
            latency_ms={
                "asr": round(asr_ms, 3),
                "rag": round(rag_ms, 3),
                "tts": round(tts_ms, 3),
                "total": round((time.perf_counter() - started) * 1000, 3),
            },
        )
        if trace_id:
            turn.latency_ms["trace_id"] = trace_id
        call.turns.append(turn)
        return turn

    def _system_turn(self, call: CallSession, text: str) -> ConversationTurn:
        turn = ConversationTurn(
            tenant_id=call.tenant_id,
            call_id=call.call_id,
            turn_id=f"turn_{call.next_sequence_no():03d}",
            sequence_no=call.next_sequence_no(),
            speaker="system",
            event_type="speech",
            redacted_text=text,
        )
        call.turns.append(turn)
        return turn

    def _turn_payload(
        self,
        principal: IdentityClaims,
        call: CallSession,
        turn: ConversationTurn,
        *,
        handoff,
    ) -> dict:
        safety = dict(turn.safety_decision or {})
        return {
            **self._envelope(principal, call.correlation_id),
            "call_id": call.call_id,
            "turn_id": turn.turn_id,
            "call_state": call.state,
            "ai_action": turn.ai_action,
            "ai_response_text": turn.ai_response_text,
            "tts_audio_ref": turn.tts_audio_ref,
            "citations": [c.public() for c in turn.citations],
            "handoff": (
                {
                    "handoff_package_id": handoff.handoff_package_id,
                    "reason": handoff.reason,
                    "destination_type": handoff.destination_type,
                    "destination_id": handoff.destination_id,
                    "status": handoff.status,
                }
                if handoff
                else None
            ),
            "safety": {
                "answered_with_evidence": bool(safety.get("answered_with_evidence")),
                "blocked_reason": safety.get("blocked_reason"),
            },
        }

    def _phone_citations(self, raw: list[dict]) -> tuple[tuple[PhoneCitationRef, ...], bool]:
        refs: list[PhoneCitationRef] = []
        dropped_blocked = False
        for c in raw:
            approval = c.get("approval_status")
            approval_str = str(approval).lower() if approval else None
            if approval_str in _BLOCKED_APPROVAL_STATUSES:
                dropped_blocked = True
                continue
            refs.append(
                PhoneCitationRef(
                    source_id=str(c.get("source_id") or ""),
                    document_id=str(c.get("document_id") or ""),
                    chunk_id=str(c.get("chunk_id") or ""),
                    version=str(c.get("version")) if c.get("version") is not None else None,
                    retrieval_score=float(c.get("retrieval_score") or 0.0),
                    approval_status=approval_str,
                    effective_date=(
                        str(c.get("effective_date")) if c.get("effective_date") else None
                    ),
                )
            )
        return tuple(refs), dropped_blocked

    def _last_answer_citations(self, call: CallSession) -> tuple[PhoneCitationRef, ...]:
        for turn in reversed(call.turns):
            if turn.speaker == "ai" and turn.ai_action == "answer_with_citations":
                return turn.citations
        return ()

    def _slot_value(self, text: str) -> str:
        """Prefer an identifier-like token (契約番号 C-123 etc.) over the whole utterance."""
        match = re.search(r"[A-Za-z]{1,4}-\d+[A-Za-z0-9-]*|\b\d{4,}\b", text)
        return match.group(0) if match else text.strip()

    def _slot_prompt(self, version: ScenarioVersion | None, slot: str) -> str:
        if version:
            for item in version.required_slots:
                if str(item.get("slot") or "") == slot and item.get("prompt"):
                    return str(item["prompt"])
        return f"{slot} を教えてください。"

    def _enabled_reasons(self, version: ScenarioVersion | None) -> set[str]:
        if not version or not version.handoff_conditions:
            return set()
        return {
            str(c.get("reason") or "")
            for c in version.handoff_conditions
            if c.get("enabled", True)
        }

    def _has_answer(self, call: CallSession) -> bool:
        return any(
            t.speaker == "ai" and t.ai_action == "answer_with_citations" for t in call.turns
        )

    def _update_summary(self, call: CallSession) -> None:
        caller_lines = [
            t.redacted_text for t in call.turns if t.speaker == "caller" and t.redacted_text
        ]
        call.summary = " / ".join(caller_lines[-3:])

    def _envelope(self, principal: IdentityClaims, correlation_id: str) -> dict:
        return {
            "api_version": "v1",
            "tenant_id": principal.tenant_id,
            "correlation_id": correlation_id,
        }

    def _can_read_call(self, principal: IdentityClaims) -> bool:
        return self._has_any_role(principal, CALL_READ_ROLES)

    def _has_any_role(self, principal: IdentityClaims, roles: frozenset[str]) -> bool:
        return bool(set(principal.roles) & roles)
