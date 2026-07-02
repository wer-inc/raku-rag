"""T015/T032/T045 — Phone persistence adapters.

Deterministic in-memory repositories are the MVP truth (Tier A: no DB dependency); the Postgres
mapping boundary targets the RLS tables from ``infra/db/migrations/postgres/0017_phone_rag.sql``
and follows the chatbot persistence precedent (`raku_rag.persistence.chatbot`): every query runs
after ``_use_tenant`` so RLS enforces tenant isolation even if a WHERE clause is wrong.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from raku_rag.phone.domain import (
    CallScenario,
    CallSession,
    ConversationTurn,
    HandoffPackage,
    PhoneCitationRef,
    QualityEvaluation,
    ScenarioVersion,
)


@dataclass
class InMemoryPhoneCallRepository:
    """Tenant-keyed call/turn/handoff storage (CallRepository contract)."""

    _calls: dict[tuple[str, str], CallSession] = field(default_factory=dict)
    _handoffs: dict[tuple[str, str], HandoffPackage] = field(default_factory=dict)

    def save_call(self, call: CallSession) -> None:
        self._calls[(call.tenant_id, call.call_id)] = call

    def get_call(self, tenant_id: str, call_id: str) -> CallSession | None:
        return self._calls.get((tenant_id, call_id))

    def list_calls(self, tenant_id: str) -> list[CallSession]:
        return [
            call for (stored_tenant, _), call in self._calls.items() if stored_tenant == tenant_id
        ]

    def save_handoff(self, package: HandoffPackage) -> None:
        self._handoffs[(package.tenant_id, package.handoff_package_id)] = package

    def get_handoff(self, tenant_id: str, handoff_package_id: str) -> HandoffPackage | None:
        return self._handoffs.get((tenant_id, handoff_package_id))


@dataclass
class InMemoryPhoneScenarioRepository:
    """Tenant-keyed scenario storage (ScenarioRepository contract)."""

    _scenarios: dict[tuple[str, str], CallScenario] = field(default_factory=dict)

    def save(self, scenario: CallScenario) -> None:
        self._scenarios[(scenario.tenant_id, scenario.scenario_id)] = scenario

    def get(self, tenant_id: str, scenario_id: str) -> CallScenario | None:
        return self._scenarios.get((tenant_id, scenario_id))

    def list(self, tenant_id: str) -> list[CallScenario]:
        return sorted(
            (
                scenario
                for (stored_tenant, _), scenario in self._scenarios.items()
                if stored_tenant == tenant_id
            ),
            key=lambda s: s.scenario_id,
        )


@dataclass
class InMemoryPhoneQualityRepository:
    """Tenant-keyed QA evaluation storage (QualityRepository contract, 022 US4)."""

    _items: dict[tuple[str, str], QualityEvaluation] = field(default_factory=dict)

    def save(self, evaluation: QualityEvaluation) -> None:
        self._items[(evaluation.tenant_id, evaluation.evaluation_id)] = evaluation

    def list_for_call(self, tenant_id: str, call_id: str) -> list[QualityEvaluation]:
        return [
            e
            for (stored_tenant, _), e in self._items.items()
            if stored_tenant == tenant_id and e.call_id == call_id
        ]

    def list_all(self, tenant_id: str) -> list[QualityEvaluation]:
        return [e for (stored_tenant, _), e in self._items.items() if stored_tenant == tenant_id]


class PostgresPhoneQualityRepository:
    """phone_quality_evaluations (0017) — typed columns, RLS-forced."""

    def __init__(self, conn) -> None:
        self._conn = conn

    def save(self, evaluation: QualityEvaluation) -> None:
        from raku_rag.persistence.postgres import _use_tenant

        _use_tenant(self._conn, evaluation.tenant_id)
        with self._conn.cursor() as cur:
            cur.execute(
                "INSERT INTO tenants (tenant_id) VALUES (%s) ON CONFLICT DO NOTHING",
                (evaluation.tenant_id,),
            )
            cur.execute(
                "INSERT INTO phone_quality_evaluations "
                "(tenant_id, evaluation_id, call_id, reviewer_id, reviewed_at, "
                " answer_correctness, tone_score, handoff_appropriateness, compliance_issue, "
                " hallucination_detected, privacy_issue, suggested_fix, knowledge_gap_topics, "
                " review_status, improvement_item_id) "
                "VALUES (%s,%s,%s,%s, COALESCE(%s::timestamptz, now()), %s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (tenant_id, evaluation_id) DO UPDATE SET "
                "review_status=EXCLUDED.review_status, suggested_fix=EXCLUDED.suggested_fix, "
                "knowledge_gap_topics=EXCLUDED.knowledge_gap_topics",
                (
                    evaluation.tenant_id,
                    evaluation.evaluation_id,
                    evaluation.call_id,
                    evaluation.reviewer_id,
                    evaluation.reviewed_at or None,
                    evaluation.answer_correctness,
                    evaluation.tone_score,
                    evaluation.handoff_appropriateness,
                    evaluation.compliance_issue,
                    evaluation.hallucination_detected,
                    evaluation.privacy_issue,
                    evaluation.suggested_fix or "",
                    list(evaluation.knowledge_gap_topics),
                    evaluation.review_status,
                    evaluation.improvement_item_id or "",
                ),
            )

    def list_for_call(self, tenant_id: str, call_id: str) -> list[QualityEvaluation]:
        return self._query(tenant_id, "AND call_id = %s", (call_id,))

    def list_all(self, tenant_id: str) -> list[QualityEvaluation]:
        return self._query(tenant_id, "", ())

    def _query(self, tenant_id: str, extra: str, params: tuple) -> list[QualityEvaluation]:
        from raku_rag.persistence.postgres import _iso, _use_tenant

        _use_tenant(self._conn, tenant_id)
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT tenant_id, evaluation_id, call_id, reviewer_id, reviewed_at, "
                "answer_correctness, tone_score, handoff_appropriateness, compliance_issue, "
                "hallucination_detected, privacy_issue, suggested_fix, knowledge_gap_topics, "
                "review_status, improvement_item_id "
                f"FROM phone_quality_evaluations WHERE tenant_id = %s {extra} "
                "ORDER BY reviewed_at DESC",
                (tenant_id, *params),
            )
            rows = cur.fetchall()
        out: list[QualityEvaluation] = []
        for row in rows:
            out.append(
                QualityEvaluation(
                    tenant_id=row[0],
                    evaluation_id=row[1],
                    call_id=row[2],
                    reviewer_id=row[3],
                    reviewed_at=_iso(row[4]) or "",
                    answer_correctness=row[5],
                    tone_score=row[6],
                    handoff_appropriateness=row[7],
                    compliance_issue=bool(row[8]),
                    hallucination_detected=bool(row[9]),
                    privacy_issue=bool(row[10]),
                    suggested_fix=(row[11] or None),
                    knowledge_gap_topics=list(row[12] or []),
                    review_status=row[13],
                    improvement_item_id=(row[14] or None),
                )
            )
        return out


class PostgresPhoneCallRepository:
    """Postgres mapping boundary for calls/turns/handoffs (0017_phone_rag.sql, RLS-forced).

    Same CallRepository contract as the in-memory adapter; used when the answer-service runs over
    a real Postgres pool. Turns and citations are persisted as JSONB alongside the session row.
    """

    def __init__(self, conn) -> None:
        self._conn = conn

    # -- calls ------------------------------------------------------------------------------------

    def save_call(self, call: CallSession) -> None:
        from raku_rag.persistence.postgres import _use_tenant

        _use_tenant(self._conn, call.tenant_id)
        with self._conn.cursor() as cur:
            cur.execute(
                "INSERT INTO tenants (tenant_id) VALUES (%s) ON CONFLICT DO NOTHING",
                (call.tenant_id,),
            )
            cur.execute(
                "INSERT INTO phone_call_sessions "
                "(tenant_id, call_id, correlation_id, channel, provider, "
                " caller_phone_number_masked, customer_id, state, intent, scenario_id, "
                " scenario_version_id, summary, resolution_status, handoff_required, "
                " handoff_reason, handoff_destination, handoff_package_id, recording_enabled, "
                " recording_disclosure_played, transcript_redaction_status, turns, "
                " started_at, answered_at, ended_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,"
                " COALESCE(%s::timestamptz, now()), %s::timestamptz, %s::timestamptz) "
                "ON CONFLICT (tenant_id, call_id) DO UPDATE SET "
                "state=EXCLUDED.state, intent=EXCLUDED.intent, summary=EXCLUDED.summary, "
                "resolution_status=EXCLUDED.resolution_status, "
                "handoff_required=EXCLUDED.handoff_required, "
                "handoff_reason=EXCLUDED.handoff_reason, "
                "handoff_destination=EXCLUDED.handoff_destination, "
                "handoff_package_id=EXCLUDED.handoff_package_id, "
                "transcript_redaction_status=EXCLUDED.transcript_redaction_status, "
                "turns=EXCLUDED.turns, answered_at=EXCLUDED.answered_at, "
                "ended_at=EXCLUDED.ended_at, updated_at=now()",
                (
                    call.tenant_id,
                    call.call_id,
                    call.correlation_id,
                    call.channel,
                    call.provider,
                    call.caller_phone_number_masked or "",
                    call.customer_id or "",
                    call.state,
                    call.intent or "",
                    call.scenario_id or "",
                    call.scenario_version_id or "",
                    call.summary,
                    call.resolution_status or "",
                    call.handoff_required,
                    call.handoff_reason or "",
                    call.handoff_destination or "",
                    call.handoff_package_id or "",
                    call.recording_enabled,
                    call.recording_disclosure_played,
                    call.transcript_redaction_status,
                    json.dumps([_turn_to_row(t) for t in call.turns]),
                    call.started_at,
                    call.answered_at,
                    call.ended_at,
                ),
            )

    def get_call(self, tenant_id: str, call_id: str) -> CallSession | None:
        from raku_rag.persistence.postgres import _use_tenant

        _use_tenant(self._conn, tenant_id)
        with self._conn.cursor() as cur:
            cur.execute(
                f"SELECT {_CALL_COLUMNS} FROM phone_call_sessions "
                "WHERE tenant_id = %s AND call_id = %s",
                (tenant_id, call_id),
            )
            row = cur.fetchone()
        return _row_to_call(row) if row else None

    def list_calls(self, tenant_id: str) -> list[CallSession]:
        from raku_rag.persistence.postgres import _use_tenant

        _use_tenant(self._conn, tenant_id)
        with self._conn.cursor() as cur:
            cur.execute(
                f"SELECT {_CALL_COLUMNS} FROM phone_call_sessions "
                "WHERE tenant_id = %s ORDER BY started_at DESC",
                (tenant_id,),
            )
            return [_row_to_call(row) for row in cur.fetchall()]

    # -- handoffs ----------------------------------------------------------------------------------

    def save_handoff(self, package: HandoffPackage) -> None:
        from raku_rag.persistence.postgres import _use_tenant

        _use_tenant(self._conn, package.tenant_id)
        with self._conn.cursor() as cur:
            cur.execute(
                "INSERT INTO phone_handoff_packages "
                "(tenant_id, handoff_package_id, call_id, status, reason, priority, "
                " destination_type, destination_id, caller_phone_number_masked, customer_id, "
                " intent, summary, transcript_excerpt_redacted, confirmed_slots, citations, "
                " sentiment, recommended_next_action, operator_id, accepted_at, failure_reason) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,"
                " %s::timestamptz, %s) "
                "ON CONFLICT (tenant_id, handoff_package_id) DO UPDATE SET "
                "status=EXCLUDED.status, operator_id=EXCLUDED.operator_id, "
                "accepted_at=EXCLUDED.accepted_at, failure_reason=EXCLUDED.failure_reason, "
                "destination_id=EXCLUDED.destination_id, "
                # Content fields must follow too — delete-request (FR-047) re-saves the package
                # with summary/excerpt/slots blanked; dropping them here would leak the excerpt.
                "summary=EXCLUDED.summary, "
                "transcript_excerpt_redacted=EXCLUDED.transcript_excerpt_redacted, "
                "confirmed_slots=EXCLUDED.confirmed_slots",
                (
                    package.tenant_id,
                    package.handoff_package_id,
                    package.call_id,
                    package.status,
                    package.reason,
                    package.priority,
                    package.destination_type,
                    package.destination_id,
                    package.caller_phone_number_masked or "",
                    package.customer_id or "",
                    package.intent or "",
                    package.summary,
                    package.transcript_excerpt_redacted,
                    json.dumps(dict(package.confirmed_slots)),
                    json.dumps([c.public() for c in package.citations]),
                    package.sentiment or "",
                    package.recommended_next_action or "",
                    package.operator_id or "",
                    package.accepted_at,
                    package.failure_reason or "",
                ),
            )

    def get_handoff(self, tenant_id: str, handoff_package_id: str) -> HandoffPackage | None:
        from raku_rag.persistence.postgres import _use_tenant

        _use_tenant(self._conn, tenant_id)
        with self._conn.cursor() as cur:
            cur.execute(
                f"SELECT {_HANDOFF_COLUMNS} FROM phone_handoff_packages "
                "WHERE tenant_id = %s AND handoff_package_id = %s",
                (tenant_id, handoff_package_id),
            )
            row = cur.fetchone()
        return _row_to_handoff(row) if row else None


class PostgresPhoneScenarioRepository:
    """Postgres mapping boundary for scenarios (versions persisted as JSONB payloads)."""

    def __init__(self, conn) -> None:
        self._conn = conn

    def save(self, scenario: CallScenario) -> None:
        from raku_rag.persistence.postgres import _use_tenant

        _use_tenant(self._conn, scenario.tenant_id)
        with self._conn.cursor() as cur:
            cur.execute(
                "INSERT INTO tenants (tenant_id) VALUES (%s) ON CONFLICT DO NOTHING",
                (scenario.tenant_id,),
            )
            cur.execute(
                "INSERT INTO phone_call_scenarios "
                "(tenant_id, scenario_id, name, intent, description, status, "
                " active_version_id, owner_group, created_by, versions) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (tenant_id, scenario_id) DO UPDATE SET "
                "name=EXCLUDED.name, intent=EXCLUDED.intent, description=EXCLUDED.description, "
                "status=EXCLUDED.status, active_version_id=EXCLUDED.active_version_id, "
                "owner_group=EXCLUDED.owner_group, versions=EXCLUDED.versions, updated_at=now()",
                (
                    scenario.tenant_id,
                    scenario.scenario_id,
                    scenario.name,
                    scenario.intent,
                    scenario.description or "",
                    scenario.status,
                    scenario.active_version_id or "",
                    scenario.owner_group or "",
                    scenario.created_by,
                    json.dumps({vid: v.public() for vid, v in scenario.versions.items()}),
                ),
            )

    def get(self, tenant_id: str, scenario_id: str) -> CallScenario | None:
        from raku_rag.persistence.postgres import _use_tenant

        _use_tenant(self._conn, tenant_id)
        with self._conn.cursor() as cur:
            cur.execute(
                f"SELECT {_SCENARIO_COLUMNS} FROM phone_call_scenarios "
                "WHERE tenant_id = %s AND scenario_id = %s",
                (tenant_id, scenario_id),
            )
            row = cur.fetchone()
        return _row_to_scenario(row) if row else None

    def list(self, tenant_id: str) -> list[CallScenario]:
        from raku_rag.persistence.postgres import _use_tenant

        _use_tenant(self._conn, tenant_id)
        with self._conn.cursor() as cur:
            cur.execute(
                f"SELECT {_SCENARIO_COLUMNS} FROM phone_call_scenarios "
                "WHERE tenant_id = %s ORDER BY scenario_id",
                (tenant_id,),
            )
            return [_row_to_scenario(row) for row in cur.fetchall()]


# --- row mapping helpers --------------------------------------------------------------------------

_CALL_COLUMNS = (
    "tenant_id, call_id, correlation_id, channel, provider, caller_phone_number_masked, "
    "customer_id, state, intent, scenario_id, scenario_version_id, summary, resolution_status, "
    "handoff_required, handoff_reason, handoff_destination, handoff_package_id, "
    "recording_enabled, recording_disclosure_played, transcript_redaction_status, turns, "
    "started_at, answered_at, ended_at"
)

_HANDOFF_COLUMNS = (
    "tenant_id, handoff_package_id, call_id, status, reason, priority, destination_type, "
    "destination_id, caller_phone_number_masked, customer_id, intent, summary, "
    "transcript_excerpt_redacted, confirmed_slots, citations, sentiment, "
    "recommended_next_action, operator_id, accepted_at, failure_reason, created_at"
)

_SCENARIO_COLUMNS = (
    "tenant_id, scenario_id, name, intent, description, status, active_version_id, "
    "owner_group, created_by, versions, created_at, updated_at"
)


def _turn_to_row(turn: ConversationTurn) -> dict:
    return {
        "turn_id": turn.turn_id,
        "sequence_no": turn.sequence_no,
        "speaker": turn.speaker,
        "event_type": turn.event_type,
        "asr_text_redacted": turn.asr_text_redacted,
        "asr_confidence": turn.asr_confidence,
        "dtmf_digits": turn.dtmf_digits,
        "redacted_text": turn.redacted_text,
        "ai_action": turn.ai_action,
        "ai_response_text": turn.ai_response_text,
        "speech_text": turn.speech_text,
        "tts_audio_ref": turn.tts_audio_ref,
        "intent": turn.intent,
        "sentiment": turn.sentiment,
        "citations": [c.public() for c in turn.citations],
        "safety_decision": turn.safety_decision,
        "handoff_reason": turn.handoff_reason,
        "latency_ms": dict(turn.latency_ms),
        "barge_in": turn.barge_in,
        "created_at": turn.created_at,
    }


def _row_to_turn(tenant_id: str, call_id: str, data: dict) -> ConversationTurn:
    return ConversationTurn(
        tenant_id=tenant_id,
        call_id=call_id,
        turn_id=str(data.get("turn_id") or ""),
        sequence_no=int(data.get("sequence_no") or 0),
        speaker=str(data.get("speaker") or "caller"),
        event_type=str(data.get("event_type") or "speech"),
        asr_text_redacted=data.get("asr_text_redacted"),
        asr_confidence=data.get("asr_confidence"),
        dtmf_digits=data.get("dtmf_digits"),
        redacted_text=data.get("redacted_text"),
        ai_action=data.get("ai_action"),
        ai_response_text=data.get("ai_response_text"),
        speech_text=data.get("speech_text"),
        tts_audio_ref=data.get("tts_audio_ref"),
        intent=data.get("intent"),
        sentiment=data.get("sentiment"),
        citations=tuple(
            PhoneCitationRef(
                source_id=str(c.get("source_id") or ""),
                document_id=str(c.get("document_id") or ""),
                chunk_id=str(c.get("chunk_id") or ""),
                version=c.get("version"),
                retrieval_score=float(c.get("retrieval_score") or 0.0),
                approval_status=c.get("approval_status"),
                effective_date=c.get("effective_date"),
                snippet_redacted=c.get("snippet_redacted"),
            )
            for c in data.get("citations") or []
        ),
        safety_decision=data.get("safety_decision"),
        handoff_reason=data.get("handoff_reason"),
        latency_ms=dict(data.get("latency_ms") or {}),
        barge_in=bool(data.get("barge_in")),
        created_at=str(data.get("created_at") or ""),
    )


def _row_to_call(row) -> CallSession:
    from raku_rag.persistence.postgres import _iso

    data = dict(zip([c.strip() for c in _CALL_COLUMNS.split(",")], row))
    turns_raw = data.get("turns") or []
    if isinstance(turns_raw, str):
        turns_raw = json.loads(turns_raw)
    call = CallSession(
        tenant_id=data["tenant_id"],
        call_id=data["call_id"],
        correlation_id=data["correlation_id"],
        channel=data["channel"],
        provider=data["provider"],
        caller_phone_number_masked=data.get("caller_phone_number_masked") or None,
        customer_id=data.get("customer_id") or None,
        state=data["state"],
        intent=data.get("intent") or None,
        scenario_id=data.get("scenario_id") or None,
        scenario_version_id=data.get("scenario_version_id") or None,
        summary=data.get("summary") or "",
        resolution_status=data.get("resolution_status") or None,
        handoff_required=bool(data.get("handoff_required")),
        handoff_reason=data.get("handoff_reason") or None,
        handoff_destination=data.get("handoff_destination") or None,
        handoff_package_id=data.get("handoff_package_id") or None,
        recording_enabled=bool(data.get("recording_enabled")),
        recording_disclosure_played=bool(data.get("recording_disclosure_played")),
        transcript_redaction_status=data.get("transcript_redaction_status") or "not_needed",
        started_at=_iso(data.get("started_at")) or "",
        # ``_iso(None)`` returns "" — normalize back to None or the next save_call would write an
        # empty string into a timestamptz column (caught by the real-PG live smoke).
        answered_at=_iso(data.get("answered_at")) or None,
        ended_at=_iso(data.get("ended_at")) or None,
    )
    call.turns = [_row_to_turn(call.tenant_id, call.call_id, t) for t in turns_raw]
    return call


def _row_to_handoff(row) -> HandoffPackage:
    from raku_rag.persistence.postgres import _iso

    data = dict(zip([c.strip() for c in _HANDOFF_COLUMNS.split(",")], row))
    slots = data.get("confirmed_slots") or {}
    if isinstance(slots, str):
        slots = json.loads(slots)
    citations = data.get("citations") or []
    if isinstance(citations, str):
        citations = json.loads(citations)
    return HandoffPackage(
        tenant_id=data["tenant_id"],
        handoff_package_id=data["handoff_package_id"],
        call_id=data["call_id"],
        reason=data["reason"],
        status=data["status"],
        priority=data["priority"],
        destination_type=data["destination_type"],
        destination_id=data["destination_id"],
        caller_phone_number_masked=data.get("caller_phone_number_masked") or None,
        customer_id=data.get("customer_id") or None,
        intent=data.get("intent") or None,
        summary=data.get("summary") or "",
        transcript_excerpt_redacted=data.get("transcript_excerpt_redacted") or "",
        confirmed_slots=dict(slots),
        citations=tuple(
            PhoneCitationRef(
                source_id=str(c.get("source_id") or ""),
                document_id=str(c.get("document_id") or ""),
                chunk_id=str(c.get("chunk_id") or ""),
                version=c.get("version"),
                retrieval_score=float(c.get("retrieval_score") or 0.0),
                approval_status=c.get("approval_status"),
                effective_date=c.get("effective_date"),
            )
            for c in citations
        ),
        sentiment=data.get("sentiment") or None,
        recommended_next_action=data.get("recommended_next_action") or None,
        operator_id=data.get("operator_id") or None,
        accepted_at=_iso(data.get("accepted_at")) or None,
        failure_reason=data.get("failure_reason") or None,
        created_at=_iso(data.get("created_at")) or "",
    )


def _row_to_scenario(row) -> CallScenario:
    from raku_rag.persistence.postgres import _iso

    data = dict(zip([c.strip() for c in _SCENARIO_COLUMNS.split(",")], row))
    versions_raw = data.get("versions") or {}
    if isinstance(versions_raw, str):
        versions_raw = json.loads(versions_raw)
    scenario = CallScenario(
        tenant_id=data["tenant_id"],
        scenario_id=data["scenario_id"],
        name=data["name"],
        intent=data["intent"],
        description=data.get("description") or None,
        status=data["status"],
        active_version_id=data.get("active_version_id") or None,
        owner_group=data.get("owner_group") or None,
        created_by=data.get("created_by") or "",
        created_at=_iso(data.get("created_at")) or "",
        updated_at=_iso(data.get("updated_at")) or "",
    )
    for version_id, payload in versions_raw.items():
        scenario.versions[version_id] = ScenarioVersion(
            tenant_id=scenario.tenant_id,
            scenario_id=scenario.scenario_id,
            scenario_version_id=version_id,
            version_number=int(payload.get("version_number") or 0),
            status=str(payload.get("status") or "draft"),
            entry_conditions=[dict(c) for c in payload.get("entry_conditions") or []],
            steps=[dict(s) for s in payload.get("steps") or []],
            required_slots=[dict(s) for s in payload.get("required_slots") or []],
            branch_conditions=[dict(c) for c in payload.get("branch_conditions") or []],
            allowed_actions=[str(a) for a in payload.get("allowed_actions") or []],
            handoff_conditions=[dict(c) for c in payload.get("handoff_conditions") or []],
            fallback_message=str(payload.get("fallback_message") or ""),
            response_templates=[dict(t) for t in payload.get("response_templates") or []],
            approved_by=payload.get("approved_by"),
            approved_at=payload.get("approved_at"),
            published_by=payload.get("published_by"),
            published_at=payload.get("published_at"),
            scheduled_publish_at=payload.get("scheduled_publish_at"),
            supersedes_version_id=payload.get("supersedes_version_id"),
            rollback_target_version_id=payload.get("rollback_target_version_id"),
            created_by=str(payload.get("created_by") or ""),
            created_at=str(payload.get("created_at") or ""),
        )
    return scenario
