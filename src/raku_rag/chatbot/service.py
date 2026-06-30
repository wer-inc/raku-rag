"""Deterministic P0 ChatBot orchestration over the existing RAG answer contract.

The ChatBot layer owns conversation progress, scenario state, and handoff/ticket stubs. It does
not own retrieval, ACL, groundedness, document lifecycle, or citations; those remain behind the
injected RAG answer callback.
"""

from __future__ import annotations

import hashlib
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable
from urllib.parse import urlparse

from raku_rag.domain.models import IdentityClaims
from raku_rag.persistence.chatbot import (
    ChatbotSourcePolicyRepository,
    InMemoryChatbotSourcePolicyRepository,
)

RagAnswerer = Callable[[IdentityClaims, str, str | None], dict]

SESSION_ADMIN_ROLES = {"ops_owner", "tenant_admin", "reviewer"}
HANDOFF_READ_ROLES = {"operator", "ops_owner", "tenant_admin"}
METRICS_ROLES = {"ops_owner", "tenant_admin"}
SOURCE_POLICY_ROLES = {"tenant_admin", "scenario_admin", "data_admin"}
SCENARIO_MANAGE_ROLES = {"tenant_admin", "scenario_admin"}
SCENARIO_APPROVE_ROLES = {"tenant_admin", "scenario_approver"}
EXPORT_DELETE_ROLES = {"tenant_admin", "audit_admin"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


EMAIL_RE = re.compile(r"([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})", re.IGNORECASE)
CARD_RE = re.compile(r"\b(?:\d[ -]*?){13,19}\b")
SECRET_RE = re.compile(
    r"(?i)\b(?:bearer|api[_-]?key|secret|token|password)\s*[:=]\s*[A-Za-z0-9._~+/=-]{6,}"
)
DETAILS_QUICK_REPLY_LABEL = "この根拠でもう少し詳しく"
HANDOFF_QUICK_REPLY_LABEL = "担当者に確認依頼"
FOLLOWUP_QUICK_REPLY_LABELS = {
    "details": DETAILS_QUICK_REPLY_LABEL,
    "steps": "手順だけ見る",
    "cautions": "注意点を確認",
    "criteria_table": "判断基準を表にする",
    "evidence": "根拠を確認する",
}
DETAILS_QUICK_REPLY_VALUES = {
    "details",
    "detail",
    "more_details",
    "more details",
    DETAILS_QUICK_REPLY_LABEL,
    "もう少し詳しく",
    "詳しく",
    "詳細",
}
FOLLOWUP_QUICK_REPLY_ALIASES = {
    "steps": {
        "steps",
        "procedure",
        "procedures",
        "手順",
        "手順だけ",
        "手順だけ見る",
        "作業手順",
    },
    "cautions": {
        "cautions",
        "caution",
        "注意",
        "注意点",
        "注意点を確認",
        "リスク",
        "安全注意",
    },
    "criteria_table": {
        "criteria",
        "criteria_table",
        "table",
        "判断基準",
        "判断基準を表にする",
        "基準を表にする",
        "表にする",
    },
    "evidence": {
        "evidence",
        "sources",
        "citations",
        "根拠",
        "根拠を確認",
        "根拠を確認する",
        "引用",
    },
}
PROCEDURE_TERMS = (
    "手順",
    "順",
    "点検",
    "確認",
    "交換",
    "実施",
    "測定",
    "記録",
    "停止",
    "復旧",
    "対応",
    "原因",
    "対策",
    "アラーム",
    "異常",
)
CRITERIA_TERMS = (
    "判定",
    "基準",
    "条件",
    "表",
    "閾値",
    "しきい値",
    "以上",
    "以下",
    "未満",
    "超",
    "AQL",
    "Ac=",
    "Re=",
    "N・m",
    "N·m",
    "mm",
    "℃",
    "ヶ月",
    "時間",
    "%",
)
CAUTION_TERMS = (
    "注意",
    "安全",
    "危険",
    "禁止",
    "停止",
    "異常",
    "損傷",
    "焼損",
    "漏れ",
    "超える",
    "保全",
    "高リスク",
)


def _redact(text: str) -> str:
    def redact_email(match: re.Match[str]) -> str:
        value = match.group(1)
        local, _, domain = value.partition("@")
        return f"{local[:1]}***@{domain}"

    redacted = EMAIL_RE.sub(redact_email, text)
    redacted = CARD_RE.sub("[card_redacted]", redacted)
    redacted = SECRET_RE.sub("[secret_redacted]", redacted)
    return redacted


def _tenant_body(principal: IdentityClaims, correlation_id: str) -> dict:
    return {"api_version": "v1", "tenant_id": principal.tenant_id, "correlation_id": correlation_id}


def _origin(value: str | None) -> str:
    if not value:
        return ""
    parsed = urlparse(value)
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}".lower()


@dataclass
class StoredMessage:
    message_id: str
    role: str
    content_redacted: str
    message_type: str = "text"
    ai_action: str | None = None
    citations: list[dict] = field(default_factory=list)
    quick_replies: list[dict] = field(default_factory=list)
    created_at: str = field(default_factory=_now)

    def public(self) -> dict:
        payload = {
            "message_id": self.message_id,
            "role": self.role,
            "content_redacted": self.content_redacted,
            "created_at": self.created_at,
        }
        if self.role == "assistant":
            payload.update(
                {
                    "message": self.content_redacted,
                    "message_type": self.message_type,
                    "ai_action": self.ai_action,
                    "quick_replies": list(self.quick_replies),
                    "citations": list(self.citations),
                }
            )
        elif self.citations:
            payload["citations"] = list(self.citations)
        return payload


@dataclass
class ChatSession:
    tenant_id: str
    user_id: str
    session_id: str
    channel: str = "web_chat"
    status: str = "active"
    current_intent: str | None = None
    current_step: str | None = None
    scenario_id: str | None = None
    scenario_version_id: str | None = None
    collected_slots: dict[str, str] = field(default_factory=dict)
    missing_slots: list[str] = field(default_factory=list)
    summary: str = ""
    handoff_required: bool = False
    handoff_package_id: str | None = None
    ticket: dict | None = None
    messages: list[StoredMessage] = field(default_factory=list)
    last_rag: dict | None = None
    failure_count: int = 0
    started_at: str = field(default_factory=_now)
    last_message_at: str = field(default_factory=_now)
    correlation_id: str = field(default_factory=lambda: _id("corr"))
    metadata: dict = field(default_factory=dict)

    def state(self) -> dict:
        return {
            "status": self.status,
            "response_state": "completed",
            "current_intent": self.current_intent,
            "current_step": self.current_step,
            "scenario_id": self.scenario_id,
            "scenario_version_id": self.scenario_version_id,
            "collected_slots": dict(self.collected_slots),
            "missing_slots": list(self.missing_slots),
            "summary": self.summary,
            "handoff_required": self.handoff_required,
        }


@dataclass
class ScenarioVersion:
    version_id: str
    status: str = "draft"
    required_slots: list[str] = field(default_factory=list)
    optional_slots: list[str] = field(default_factory=list)
    steps: list[dict] = field(default_factory=list)
    validation_rules: list[dict] = field(default_factory=list)
    rag_policy: dict = field(default_factory=dict)
    actions: list[dict] = field(default_factory=list)
    response_templates: dict = field(default_factory=dict)
    handoff_conditions: list[dict] = field(default_factory=list)
    updated_at: str = field(default_factory=_now)
    approved_by: str | None = None
    approved_at: str | None = None
    published_by: str | None = None
    published_at: str | None = None

    def public(self) -> dict:
        return {
            "version_id": self.version_id,
            "status": self.status,
            "required_slots": list(self.required_slots),
            "optional_slots": list(self.optional_slots),
            "steps": [dict(step) for step in self.steps],
            "validation_rules": [dict(rule) for rule in self.validation_rules],
            "rag_policy": dict(self.rag_policy),
            "actions": [dict(action) for action in self.actions],
            "response_templates": dict(self.response_templates),
            "handoff_conditions": [dict(condition) for condition in self.handoff_conditions],
            "updated_at": self.updated_at,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at,
            "published_by": self.published_by,
            "published_at": self.published_at,
        }


@dataclass
class ChatScenario:
    scenario_id: str
    name: str
    intents: list[str]
    status: str = "draft"
    active_version_id: str | None = None
    versions: dict[str, ScenarioVersion] = field(default_factory=dict)

    def public(self, tenant_id: str) -> dict:
        return {
            "tenant_id": tenant_id,
            "scenario_id": self.scenario_id,
            "name": self.name,
            "intents": list(self.intents),
            "status": self.status,
            "active_version_id": self.active_version_id,
            "versions": [version.public() for version in self.versions.values()],
        }

    def version(self, version_id: str) -> ScenarioVersion | None:
        return self.versions.get(version_id)

    def active_version(self) -> ScenarioVersion | None:
        if not self.active_version_id:
            return None
        return self.versions.get(self.active_version_id)


class ChatbotService:
    def __init__(
        self,
        rag_answerer: RagAnswerer,
        source_policy_repository: ChatbotSourcePolicyRepository | None = None,
    ) -> None:
        self._rag_answerer = rag_answerer
        self._sessions: dict[tuple[str, str], ChatSession] = {}
        self._handoffs: dict[tuple[str, str], dict] = {}
        self._feedback: dict[tuple[str, str], dict] = {}
        self._source_policies: dict[tuple[str, str], dict] = {}
        self._source_policy_repo = source_policy_repository or InMemoryChatbotSourcePolicyRepository(
            self._source_policies
        )
        self._scenarios: dict[tuple[str, str], ChatScenario] = {}
        self._seed_scenarios()

    # --- sessions and turns -------------------------------------------------

    def create_session(self, principal: IdentityClaims, body: dict) -> tuple[int, dict]:
        channel = str(body.get("channel") or "web_chat")
        metadata = dict(body.get("metadata") or {})
        if channel == "public_widget" and (
            "chat_anonymous" not in principal.roles
            or metadata.get("chat_mode") != "external_anonymous"
        ):
            channel = "web_chat"
        session = ChatSession(
            tenant_id=principal.tenant_id,
            user_id=principal.user_id,
            session_id=_id("chat"),
            channel=channel,
            metadata=metadata,
        )
        self._sessions[(principal.tenant_id, session.session_id)] = session

        initial = str(body.get("initial_message") or "").strip()
        if initial:
            _, response = self.submit_message(
                principal,
                session.session_id,
                {
                    "message": initial,
                    "client_message_id": body.get("client_message_id") or "initial",
                    "collection_id": body.get("collection_id"),
                },
            )
            response["processed_initial_message"] = True
            return 201, response

        response = {
            **_tenant_body(principal, session.correlation_id),
            "session_id": session.session_id,
            "status": session.status,
            "processed_initial_message": False,
            "state": session.state(),
        }
        return 201, response

    def submit_message(
        self, principal: IdentityClaims, session_id: str, body: dict
    ) -> tuple[int, dict]:
        try:
            session = self._require_session(principal, session_id)
        except KeyError:
            return 404, {"error": "not_found"}
        if session.status in {"resolved", "ticket_created", "closed"}:
            return 409, {"error": "session_terminal"}

        text = str(body.get("message") or "").strip()
        if not text:
            return 400, {"error": "message_required"}

        display_text = self._display_text_for_quick_reply(text)
        rag_text = self._expand_quick_reply_for_rag(session, text)

        user_message = self._add_message(session, "user", display_text)
        intent = self._classify_intent(rag_text, session.current_intent)
        session.current_intent = intent if intent != "confirm" else session.current_intent
        session.last_message_at = _now()

        if intent == "human_handoff":
            handoff = self._create_handoff(
                session, reason="customer_requested_human", comment=display_text, priority="normal"
            )
            assistant = self._assistant(
                session,
                "確認依頼を受け付けました。担当者が会話内容と確認済み情報を確認します。",
                "handoff",
                quick_replies=[],
            )
            return 200, self._turn_response(
                principal, session, user_message, assistant, handoff=handoff
            )

        if intent == "high_risk":
            handoff = self._create_handoff(
                session, reason="unsupported_high_risk", comment=display_text, priority="high"
            )
            assistant = self._assistant(
                session,
                "この内容はBotだけでは確定できません。担当者に確認依頼しました。",
                "handoff",
                quick_replies=[],
            )
            return 200, self._turn_response(
                principal, session, user_message, assistant, handoff=handoff
            )

        if intent in {"cancel_subscription", "confirm"} or session.scenario_id == "cancel-basic":
            assistant, ticket = self._run_cancel_scenario(session, display_text, intent)
            return 200, self._turn_response(
                principal, session, user_message, assistant, ticket=ticket
            )

        assistant, rag, handoff = self._run_rag_turn(
            principal,
            session,
            rag_text,
            collection_id=body.get("collection_id") or session.metadata.get("collection_id"),
        )
        return 200, self._turn_response(
            principal, session, user_message, assistant, rag=rag, handoff=handoff
        )

    def get_session(self, principal: IdentityClaims, session_id: str) -> tuple[int, dict]:
        session = self._sessions.get((principal.tenant_id, session_id))
        if not session or not self._can_read_session(principal, session):
            return 404, {"error": "not_found"}
        return 200, self._session_detail(principal, session)

    def list_sessions(
        self, principal: IdentityClaims, query: dict | None = None
    ) -> tuple[int, dict]:
        if not self._has_any_role(principal, SESSION_ADMIN_ROLES):
            return 403, {"error": "chat_role_required"}
        query = query or {}
        intent = str(
            (query.get("intent") or [""])[0]
            if isinstance(query.get("intent"), list)
            else query.get("intent") or ""
        )
        status = str(
            (query.get("status") or [""])[0]
            if isinstance(query.get("status"), list)
            else query.get("status") or ""
        )
        items = []
        for (tenant_id, _), session in self._sessions.items():
            if tenant_id != principal.tenant_id or not self._can_read_session(principal, session):
                continue
            if intent and session.current_intent != intent:
                continue
            if status and session.status != status:
                continue
            items.append(
                {
                    "session_id": session.session_id,
                    "started_at": session.started_at,
                    "last_message_at": session.last_message_at,
                    "current_intent": session.current_intent,
                    "status": session.status,
                    "resolution_status": session.status,
                    "handoff_required": session.handoff_required,
                    "scenario_version_id": session.scenario_version_id,
                }
            )
        return 200, {
            **_tenant_body(principal, _id("corr")),
            "items": sorted(items, key=lambda x: x["last_message_at"], reverse=True),
            "next_cursor": None,
        }

    # --- handoff, feedback, metrics ----------------------------------------

    def request_handoff(
        self, principal: IdentityClaims, session_id: str, body: dict
    ) -> tuple[int, dict]:
        try:
            session = self._require_session(principal, session_id)
        except KeyError:
            return 404, {"error": "not_found"}
        reason = str(body.get("reason") or "customer_requested_human")
        handoff = self._create_handoff(
            session, reason=reason, comment=str(body.get("comment") or "")
        )
        return 200, {
            **_tenant_body(principal, _id("corr")),
            "session_id": session.session_id,
            "handoff_package_id": handoff["handoff_package_id"],
            "status": handoff["status"],
            "reason": handoff["reason"],
        }

    def get_handoff(self, principal: IdentityClaims, handoff_id: str) -> tuple[int, dict]:
        if not self._has_any_role(principal, HANDOFF_READ_ROLES):
            return 403, {"error": "chat_role_required"}
        handoff = self._handoffs.get((principal.tenant_id, handoff_id))
        if not handoff:
            return 404, {"error": "not_found"}
        return 200, {**_tenant_body(principal, _id("corr")), **handoff}

    def submit_feedback(
        self, principal: IdentityClaims, session_id: str, body: dict
    ) -> tuple[int, dict]:
        try:
            session = self._require_session(principal, session_id)
        except KeyError:
            return 404, {"error": "not_found"}
        evaluation_id = _id("eval")
        issue_type = str(body.get("issue_type") or "")
        improvement_id = _id("imp") if issue_type == "rag_gap" else None
        item = {
            "tenant_id": principal.tenant_id,
            "evaluation_id": evaluation_id,
            "session_id": session.session_id,
            "message_id": body.get("message_id"),
            "rating": body.get("rating"),
            "issue_type": issue_type,
            "comment_redacted": _redact(str(body.get("comment") or "")),
            "improvement_item_id": improvement_id,
            "created_at": _now(),
        }
        self._feedback[(principal.tenant_id, evaluation_id)] = item
        return 201, {
            **_tenant_body(principal, _id("corr")),
            "evaluation_id": evaluation_id,
            "improvement_item_id": improvement_id,
        }

    def metrics(self, principal: IdentityClaims) -> tuple[int, dict]:
        if not self._has_any_role(principal, METRICS_ROLES):
            return 403, {"error": "chat_role_required"}
        sessions = [
            s
            for (tenant_id, _), s in self._sessions.items()
            if tenant_id == principal.tenant_id and self._can_read_session(principal, s)
        ]
        count = len(sessions)
        handoff_count = sum(1 for s in sessions if s.handoff_required)
        unanswered_count = sum(
            1 for s in sessions if s.last_rag and not s.last_rag.get("answerable")
        )
        resolved_count = sum(1 for s in sessions if s.status in {"resolved", "ticket_created"})
        rag_count = sum(1 for s in sessions if s.last_rag)
        rag_answerable = sum(1 for s in sessions if s.last_rag and s.last_rag.get("answerable"))
        turns = sum(len([m for m in s.messages if m.role == "user"]) for s in sessions)
        intents: dict[str, int] = {}
        reasons: dict[str, int] = {}
        for s in sessions:
            if s.current_intent:
                intents[s.current_intent] = intents.get(s.current_intent, 0) + 1
            if s.handoff_package_id:
                h = self._handoffs.get((s.tenant_id, s.handoff_package_id))
                if h:
                    reasons[h["reason"]] = reasons.get(h["reason"], 0) + 1
        return 200, {
            **_tenant_body(principal, _id("corr")),
            "summary": {
                "conversation_count": count,
                "bot_resolution_rate": (resolved_count / count) if count else 0.0,
                "handoff_rate": (handoff_count / count) if count else 0.0,
                "unanswered_rate": (unanswered_count / count) if count else 0.0,
                "rag_answerable_rate": (rag_answerable / rag_count) if rag_count else 0.0,
                "average_turns": (turns / count) if count else 0.0,
                "p95_response_latency_ms": 0,
            },
            "top_intents": [{"key": k, "count": v} for k, v in sorted(intents.items())],
            "top_handoff_reasons": [{"key": k, "count": v} for k, v in sorted(reasons.items())],
        }

    # --- source exposure policies ------------------------------------------

    def list_source_policies(self, principal: IdentityClaims) -> tuple[int, dict]:
        if not self._has_any_role(principal, SOURCE_POLICY_ROLES):
            return 403, {"error": "chat_role_required"}
        policies = self._source_policy_repo.list(principal.tenant_id)
        return 200, {**_tenant_body(principal, _id("corr")), "items": policies}

    def upsert_source_policy(
        self, principal: IdentityClaims, policy_id: str, body: dict
    ) -> tuple[int, dict]:
        if not self._has_any_role(principal, SOURCE_POLICY_ROLES):
            return 403, {"error": "chat_role_required"}
        mode = str(body.get("exposure_mode") or "disabled")
        if mode not in {
            "disabled",
            "internal_authenticated",
            "external_authenticated",
            "external_anonymous",
        }:
            return 422, {"error": "invalid_exposure_mode"}
        source_id = str(body.get("source_id") or "")
        status = "draft" if source_id else "active"
        policy = {
            "policy_id": policy_id,
            "tenant_id": principal.tenant_id,
            "source_id": source_id,
            "collection_id": str(body.get("collection_id") or ""),
            "exposure_mode": mode,
            "allowed_channels": list(body.get("allowed_channels") or []),
            "allowed_scenario_ids": list(body.get("allowed_scenario_ids") or []),
            "allowed_intents": list(body.get("allowed_intents") or []),
            "required_document_tags": list(body.get("required_document_tags") or []),
            "blocked_document_tags": list(body.get("blocked_document_tags") or []),
            "require_approved_effective": bool(body.get("require_approved_effective", True)),
            "allow_obsolete_primary_evidence": bool(
                body.get("allow_obsolete_primary_evidence", False)
            ),
            "allowed_domains": list(body.get("allowed_domains") or []),
            "status": status,
            "updated_by": principal.user_id,
            "updated_at": _now(),
        }
        if source_id:
            policy["unsupported_reason"] = "source_level_filter_requires_rag_adapter_support"
        saved = self._source_policy_repo.upsert(principal.tenant_id, policy_id, policy)
        return 200, {**_tenant_body(principal, _id("corr")), **saved}

    def validate_source_policy(self, principal: IdentityClaims, body: dict) -> tuple[int, dict]:
        if not self._has_any_role(principal, SOURCE_POLICY_ROLES):
            return 403, {"error": "chat_role_required"}
        mode = str(body.get("exposure_mode") or "disabled")
        reasons = []
        if body.get("source_id"):
            reasons.append("source_level_filter_requires_rag_adapter_support")
        if mode == "external_anonymous":
            if not body.get("required_document_tags"):
                reasons.append("external_anonymous_requires_public_document_tag")
            if not body.get("allowed_domains"):
                reasons.append("external_anonymous_requires_allowed_domain")
        return 200, {
            **_tenant_body(principal, _id("corr")),
            "allowed": not reasons,
            "reasons": reasons,
        }

    # --- scenarios ----------------------------------------------------------

    def list_scenarios(self, principal: IdentityClaims) -> tuple[int, dict]:
        if not self._has_any_role(principal, SCENARIO_MANAGE_ROLES | SCENARIO_APPROVE_ROLES):
            return 403, {"error": "chat_role_required"}
        scenarios = [
            s.public(principal.tenant_id)
            for (tenant_id, _), s in self._scenarios.items()
            if tenant_id in {"*", principal.tenant_id}
        ]
        return 200, {**_tenant_body(principal, _id("corr")), "items": scenarios}

    def create_scenario(self, principal: IdentityClaims, body: dict) -> tuple[int, dict]:
        if not self._has_any_role(principal, SCENARIO_MANAGE_ROLES):
            return 403, {"error": "chat_role_required"}
        primary_intent = str(body.get("primary_intent") or "")
        scenario_id = str(
            body.get("scenario_id")
            or ("cancel-basic" if primary_intent == "cancel_subscription" else _id("scenario"))
        )
        intents = [str(x) for x in (body.get("intents") or [])]
        if primary_intent and primary_intent not in intents:
            intents.insert(0, primary_intent)
        if not intents:
            intents = ["rag_question"]
        scenario = ChatScenario(
            scenario_id=scenario_id,
            name=str(body.get("name") or scenario_id),
            intents=intents,
            status=str(body.get("status") or "draft"),
        )
        version_id = str(body.get("version_id") or "")
        if version_id:
            scenario.versions[version_id] = ScenarioVersion(
                version_id=version_id,
                status="draft",
                required_slots=self._required_slots_from_definition(body),
            )
        self._scenarios[(principal.tenant_id, scenario_id)] = scenario
        return 201, {**_tenant_body(principal, _id("corr")), **scenario.public(principal.tenant_id)}

    def upsert_scenario_version(
        self, principal: IdentityClaims, scenario_id: str, version_id: str, body: dict
    ) -> tuple[int, dict]:
        if not self._has_any_role(principal, SCENARIO_MANAGE_ROLES):
            return 403, {"error": "chat_role_required"}
        scenario = self._tenant_scenario(principal.tenant_id, scenario_id)
        if not scenario:
            return 404, {"error": "not_found"}
        existing = scenario.version(version_id)
        if existing and existing.status in {"published", "archived"}:
            return 409, {"error": "scenario_version_immutable"}

        status = existing.status if existing else "draft"
        version = ScenarioVersion(
            version_id=version_id,
            status=status,
            required_slots=self._required_slots_from_definition(
                body, fallback=existing.required_slots if existing else []
            ),
            optional_slots=[
                str(x)
                for x in (
                    body.get("optional_slots") or (existing.optional_slots if existing else [])
                )
            ],
            steps=[
                dict(step) for step in (body.get("steps") or (existing.steps if existing else []))
            ],
            validation_rules=[
                dict(rule)
                for rule in (
                    body.get("validation_rules") or (existing.validation_rules if existing else [])
                )
            ],
            rag_policy=dict(body.get("rag_policy") or (existing.rag_policy if existing else {})),
            actions=[
                dict(action)
                for action in (body.get("actions") or (existing.actions if existing else []))
            ],
            response_templates=dict(
                body.get("response_templates") or (existing.response_templates if existing else {})
            ),
            handoff_conditions=[
                dict(condition)
                for condition in (
                    body.get("handoff_conditions")
                    or (existing.handoff_conditions if existing else [])
                )
            ],
            updated_at=_now(),
            approved_by=existing.approved_by if existing else None,
            approved_at=existing.approved_at if existing else None,
            published_by=existing.published_by if existing else None,
            published_at=existing.published_at if existing else None,
        )
        scenario.versions[version_id] = version
        if not scenario.active_version_id and version.status == "published":
            scenario.active_version_id = version_id
        if scenario.status not in {"published", "scheduled"}:
            scenario.status = version.status
        return 200, {**_tenant_body(principal, _id("corr")), **scenario.public(principal.tenant_id)}

    def scenario_action(
        self, principal: IdentityClaims, scenario_id: str, version_id: str, action: str, body: dict
    ) -> tuple[int, dict]:
        if action in {"approve", "publish", "schedule", "archive"}:
            required_roles = SCENARIO_APPROVE_ROLES
        else:
            required_roles = SCENARIO_MANAGE_ROLES
        if not self._has_any_role(principal, required_roles):
            return 403, {"error": "chat_role_required"}
        scenario = self._tenant_scenario(principal.tenant_id, scenario_id)
        if not scenario:
            return 404, {"error": "not_found"}
        version = scenario.version(version_id)
        if not version:
            return 404, {"error": "not_found"}
        if action == "preview":
            msg = str(body.get("message") or "")
            slots = self._extract_slots(msg, {})
            missing = [s for s in version.required_slots if s not in slots]
            return 200, {
                **_tenant_body(principal, _id("corr")),
                "scenario_id": scenario.scenario_id,
                "version_id": version.version_id,
                "intent": self._classify_intent(msg, None),
                "collected_slots": slots,
                "missing_slots": missing,
            }
        transitions = {
            "submit-review": "in_review",
            "approve": "approved",
            "publish": "published",
            "schedule": "scheduled",
            "archive": "archived",
        }
        if action == "publish" and version.status != "approved":
            return 409, {"error": "scenario_version_not_approved"}
        if action in transitions:
            version.status = transitions[action]
            version.updated_at = _now()
            if action == "approve":
                version.approved_by = principal.user_id
                version.approved_at = version.updated_at
            if action == "publish":
                version.published_by = principal.user_id
                version.published_at = version.updated_at
                scenario.active_version_id = version.version_id
            if action == "archive" and scenario.active_version_id == version.version_id:
                scenario.active_version_id = None
            scenario.status = version.status
            return 200, {
                **_tenant_body(principal, _id("corr")),
                **scenario.public(principal.tenant_id),
            }
        return 404, {"error": "not_found"}

    def rollback_scenario(self, principal: IdentityClaims, scenario_id: str) -> tuple[int, dict]:
        if not self._has_any_role(principal, SCENARIO_APPROVE_ROLES):
            return 403, {"error": "chat_role_required"}
        scenario = self._scenarios.get((principal.tenant_id, scenario_id))
        if not scenario:
            return 404, {"error": "not_found"}
        published = [v for v in scenario.versions.values() if v.status == "published"]
        if not published:
            return 409, {"error": "scenario_version_not_approved"}
        scenario.active_version_id = published[-1].version_id
        scenario.status = "published"
        return 200, {**_tenant_body(principal, _id("corr")), **scenario.public(principal.tenant_id)}

    # --- lifecycle stubs ----------------------------------------------------

    def export_sessions(self, principal: IdentityClaims) -> tuple[int, dict]:
        if not self._has_any_role(principal, EXPORT_DELETE_ROLES):
            return 403, {"error": "chat_role_required"}
        return 200, {
            **_tenant_body(principal, _id("corr")),
            "export_job_id": _id("chat_export"),
            "status": "queued",
            "redacted": True,
        }

    def delete_request(self, principal: IdentityClaims, session_id: str) -> tuple[int, dict]:
        if not self._has_any_role(principal, EXPORT_DELETE_ROLES):
            return 403, {"error": "chat_role_required"}
        try:
            self._require_session(principal, session_id)
        except KeyError:
            return 404, {"error": "not_found"}
        return 202, {
            **_tenant_body(principal, _id("corr")),
            "session_id": session_id,
            "status": "queued",
            "redaction_requested": True,
        }

    def retention_policy(self, principal: IdentityClaims) -> tuple[int, dict]:
        if not self._has_any_role(principal, EXPORT_DELETE_ROLES):
            return 403, {"error": "chat_role_required"}
        return 200, {
            **_tenant_body(principal, _id("corr")),
            "retention_days": 365,
            "redacted_export_enabled": True,
        }

    # --- private helpers ----------------------------------------------------

    def _run_cancel_scenario(
        self, session: ChatSession, text: str, intent: str
    ) -> tuple[StoredMessage, dict | None]:
        scenario = self._tenant_scenario(session.tenant_id, session.scenario_id or "cancel-basic")
        version = scenario.active_version() if scenario else None
        required = list(version.required_slots if version else ["email", "company_name"])
        session.current_intent = "cancel_subscription"
        session.scenario_id = "cancel-basic"
        session.scenario_version_id = version.version_id if version else "csv_cancel_basic_v1"
        session.current_step = "identify_customer"
        slots = self._extract_slots(text, session.collected_slots)
        session.collected_slots.update(slots)
        session.missing_slots = [slot for slot in required if not session.collected_slots.get(slot)]

        if self._is_confirmation(text) and not session.missing_slots:
            ticket = self._create_ticket(session)
            assistant = self._assistant(
                session,
                f"受付しました。受付番号は {ticket['ticket_id']} です。担当者が内容を確認します。",
                "ticket_created",
                quick_replies=[],
            )
            session.status = "ticket_created"
            session.current_step = "ticket_created"
            return assistant, ticket

        if session.missing_slots:
            target = session.missing_slots[0]
            label = "登録メールアドレス" if target == "email" else "会社名または契約者名"
            assistant = self._assistant(
                session,
                f"承知しました。手続きを確認するため、{label}を教えてください。",
                "collect_slot",
                quick_replies=[{"label": HANDOFF_QUICK_REPLY_LABEL, "value": "handoff"}],
            )
            return assistant, None

        session.current_step = "confirm_final"
        assistant = self._assistant(
            session,
            "必要な情報が揃いました。この内容で解約受付を作成してよいですか？",
            "confirm_action",
            quick_replies=[
                {"label": "進める", "value": "confirm"},
                {"label": HANDOFF_QUICK_REPLY_LABEL, "value": "handoff"},
            ],
        )
        return assistant, None

    def _run_rag_turn(
        self,
        principal: IdentityClaims,
        session: ChatSession,
        text: str,
        collection_id: str | None,
    ) -> tuple[StoredMessage, dict, dict | None]:
        started = time.perf_counter()
        pre_rag_policy_ids = self._pre_rag_source_policy_ids(session, collection_id)
        if not pre_rag_policy_ids:
            latency_ms = int((time.perf_counter() - started) * 1000)
            rag = {
                "rag_interaction_id": _id("rag_chat"),
                "status": "insufficient_evidence",
                "answerable": False,
                "confidence": None,
                "no_answer_reason": "source_not_enabled_for_chatbot",
                "trace_id": None,
                "latency_ms": latency_ms,
                "citations": [],
                "source_policy_id": None,
            }
            session.last_rag = rag
            handoff = self._create_handoff(
                session,
                reason="source_not_enabled_for_chatbot",
                comment=text,
                priority="normal",
            )
            assistant = self._assistant(
                session,
                "承認済みの根拠だけでは回答を確定できません。担当者に確認依頼しました。",
                "handoff",
                quick_replies=[],
            )
            return assistant, rag, handoff

        rag_response = self._rag_answerer(principal, text, collection_id)
        latency_ms = int((time.perf_counter() - started) * 1000)
        raw_citations = [dict(c) for c in (rag_response.get("citations") or [])]
        citations, policy_ids = self._filter_chatbot_citations(
            session, raw_citations, collection_id
        )
        status = str(rag_response.get("status") or "temporarily_unavailable")
        source_policy_blocked = False
        if status == "ok" and raw_citations and not citations:
            status = "insufficient_evidence"
            source_policy_blocked = True
        confidence = rag_response.get("confidence")
        answerable = (
            status == "ok"
            and bool(citations)
            and bool(rag_response.get("text"))
            and (confidence is None or float(confidence) >= 0.2)
        )
        no_answer_reason = (
            None
            if answerable
            else "source_not_enabled_for_chatbot" if source_policy_blocked else status
        )
        rag = {
            "rag_interaction_id": _id("rag_chat"),
            "status": status,
            "answerable": answerable,
            "confidence": confidence,
            "no_answer_reason": no_answer_reason,
            "trace_id": rag_response.get("correlation_id"),
            "latency_ms": latency_ms,
            "citations": citations,
            "source_policy_id": ",".join(policy_ids or pre_rag_policy_ids),
        }
        session.last_rag = rag

        if answerable:
            answer_text = str(rag_response.get("text"))
            assistant = self._assistant(
                session,
                self._format_chatbot_answer(answer_text, text, collection_id, citations),
                "answer_with_citations",
                citations=citations,
                quick_replies=self._quick_replies_for_answer(text, answer_text),
            )
            return assistant, rag, None

        handoff = self._create_handoff(
            session,
            reason=no_answer_reason or "insufficient_evidence",
            comment=text,
            priority="normal",
        )
        assistant = self._assistant(
            session,
            "承認済みの根拠だけでは回答を確定できません。担当者に確認依頼しました。",
            "handoff",
            quick_replies=[],
        )
        return assistant, rag, handoff

    def _turn_response(
        self,
        principal: IdentityClaims,
        session: ChatSession,
        user_message: StoredMessage,
        assistant_message: StoredMessage,
        *,
        rag: dict | None = None,
        handoff: dict | None = None,
        ticket: dict | None = None,
    ) -> dict:
        return {
            **_tenant_body(principal, _id("corr")),
            "session_id": session.session_id,
            "status": session.status,
            "user_message_id": user_message.message_id,
            "assistant_message": {
                "message_id": assistant_message.message_id,
                "message": assistant_message.content_redacted,
                "message_type": assistant_message.message_type,
                "ai_action": assistant_message.ai_action,
                "quick_replies": list(assistant_message.quick_replies),
                "citations": list(assistant_message.citations),
            },
            "state": session.state(),
            "rag": rag or session.last_rag,
            "handoff": handoff,
            "ticket": ticket or session.ticket,
        }

    def _session_detail(self, principal: IdentityClaims, session: ChatSession) -> dict:
        return {
            **_tenant_body(principal, _id("corr")),
            "session_id": session.session_id,
            "status": session.status,
            "current_intent": session.current_intent,
            "scenario_id": session.scenario_id,
            "scenario_version_id": session.scenario_version_id,
            "summary": session.summary,
            "messages": [m.public() for m in session.messages],
            "state": session.state(),
            "handoff": (
                self._handoffs.get((session.tenant_id, session.handoff_package_id))
                if session.handoff_package_id
                else None
            ),
            "ticket": session.ticket,
        }

    def _add_message(
        self,
        session: ChatSession,
        role: str,
        text: str,
        *,
        ai_action: str | None = None,
        citations: list[dict] | None = None,
        quick_replies: list[dict] | None = None,
    ) -> StoredMessage:
        message = StoredMessage(
            message_id=_id("msg"),
            role=role,
            content_redacted=_redact(text),
            ai_action=ai_action,
            citations=list(citations or []),
            quick_replies=list(quick_replies or []),
        )
        session.messages.append(message)
        session.last_message_at = message.created_at
        session.summary = self._summary(session)
        return message

    def _assistant(
        self,
        session: ChatSession,
        text: str,
        ai_action: str,
        *,
        citations: list[dict] | None = None,
        quick_replies: list[dict] | None = None,
    ) -> StoredMessage:
        return self._add_message(
            session,
            "assistant",
            text,
            ai_action=ai_action,
            citations=citations,
            quick_replies=quick_replies,
        )

    def _format_chatbot_answer(
        self,
        answer_text: str,
        question: str,
        collection_id: str | None,
        citations: list[dict],
    ) -> str:
        answer = answer_text.strip()
        if not answer:
            return answer

        conclusion = self._strip_leading_section_label(answer)
        procedure_lines = self._extract_relevant_lines(answer, PROCEDURE_TERMS, limit=3)
        caution_lines = self._extract_relevant_lines(answer, CAUTION_TERMS, limit=3)
        evidence_lines = self._evidence_lines(citations)
        condition_lines = [
            f"参照範囲: {collection_id or '選択中の参照範囲'}",
            f"質問: {self._compact_line(question, limit=96)}",
            "承認済みデータの引用がある範囲で回答しています。",
        ]

        if not procedure_lines:
            procedure_lines = ["文書内で明示された手順は、上記の回答範囲に限定されます。"]
        if not caution_lines:
            caution_lines = ["追加の注意点は引用内で確認できる範囲に限定されます。"]

        sections = [
            ("結論", conclusion),
            ("条件", self._bullet_lines(condition_lines)),
            ("手順", self._bullet_lines(procedure_lines)),
            ("注意点", self._bullet_lines(caution_lines)),
            ("根拠", self._bullet_lines(evidence_lines or ["引用情報を確認できません。"])),
            (
                "不明点",
                self._bullet_lines(
                    ["根拠にない条件、例外、最新運用ルールは断定しません。必要なら担当者に確認依頼してください。"]
                ),
            ),
        ]
        return "\n\n".join(f"{title}:\n{body}" for title, body in sections)

    def _quick_replies_for_answer(self, question: str, answer_text: str) -> list[dict]:
        blob = f"{question}\n{answer_text}"
        actions = ["details"]
        if self._contains_any(blob, PROCEDURE_TERMS):
            actions.append("steps")
        if self._contains_any(blob, CRITERIA_TERMS):
            actions.append("criteria_table")
        if self._contains_any(blob, CAUTION_TERMS):
            actions.append("cautions")
        actions.append("evidence")

        replies: list[dict] = []
        seen: set[str] = set()
        for action in actions:
            if action in seen or action not in FOLLOWUP_QUICK_REPLY_LABELS:
                continue
            seen.add(action)
            replies.append({"label": FOLLOWUP_QUICK_REPLY_LABELS[action], "value": action})
            if len(replies) >= 4:
                break
        return replies

    def _display_text_for_quick_reply(self, text: str) -> str:
        action = self._quick_reply_action(text)
        if action:
            return FOLLOWUP_QUICK_REPLY_LABELS[action]
        return text

    def _expand_quick_reply_for_rag(self, session: ChatSession, text: str) -> str:
        action = self._quick_reply_action(text)
        if not action:
            return text

        context = self._last_answer_context(session)
        if not context:
            instruction = self._followup_instruction(action)
            return f"前回の回答について、同じ根拠に基づいて{instruction}"

        previous_question = context.get("question") or "前回の質問"
        previous_answer = context.get("answer") or ""
        document_ids = context.get("document_ids") or []
        document_hint = ""
        if document_ids:
            document_hint = " 参照文書ID: " + ", ".join(document_ids) + "。"
        answer_hint = ""
        if previous_answer:
            answer_hint = " 前回回答: " + previous_answer[:240] + "。"
        return (
            f"前回の質問「{previous_question}」について、同じ承認済み根拠に基づき、"
            f"{self._followup_instruction(action)}"
            "文書にない内容は推測しないでください。"
            f"{document_hint}{answer_hint}"
        )

    def _is_details_quick_reply(self, text: str) -> bool:
        return self._quick_reply_action(text) == "details"

    def _quick_reply_action(self, text: str) -> str | None:
        normalized = text.strip().lower()
        if normalized in DETAILS_QUICK_REPLY_VALUES:
            return "details"
        for action, aliases in FOLLOWUP_QUICK_REPLY_ALIASES.items():
            if normalized in {alias.lower() for alias in aliases}:
                return action
        return None

    def _followup_instruction(self, action: str) -> str:
        if action == "steps":
            return "手順だけを番号付きで整理してください。"
        if action == "cautions":
            return "注意点、禁止事項、安全確認、例外条件だけを整理してください。"
        if action == "criteria_table":
            return "判断基準、閾値、数値条件を表形式に近い形で整理してください。"
        if action == "evidence":
            return "根拠文書、引用箇所、根拠から言えることだけを整理してください。"
        return "結論、条件、手順、注意点、根拠をもう少し詳しく説明してください。"

    def _strip_leading_section_label(self, text: str) -> str:
        return re.sub(r"^\s*(?:結論|回答)\s*[:：]\s*", "", text.strip())

    def _extract_relevant_lines(
        self, text: str, terms: tuple[str, ...], *, limit: int
    ) -> list[str]:
        lines: list[str] = []
        for sentence in self._answer_sentences(text):
            if self._contains_any(sentence, terms):
                lines.append(self._compact_line(sentence))
            if len(lines) >= limit:
                break
        return list(dict.fromkeys(lines))

    def _answer_sentences(self, text: str) -> list[str]:
        normalized = re.sub(r"\s+", " ", text.strip())
        parts = re.findall(r"[^。！？!?\n;]+[。！？!?]?", normalized)
        sentences = [self._compact_line(part) for part in parts if part.strip()]
        return sentences or [self._compact_line(normalized)]

    def _evidence_lines(self, citations: list[dict]) -> list[str]:
        lines: list[str] = []
        for citation in citations[:3]:
            document_id = str(citation.get("document_id") or "document")
            chunk_id = citation.get("chunk_id")
            version = citation.get("version")
            suffix = []
            if version is not None:
                suffix.append(f"version {version}")
            if chunk_id:
                suffix.append(str(chunk_id))
            detail = f" ({', '.join(suffix)})" if suffix else ""
            lines.append(f"{document_id}{detail}")
        return lines

    def _bullet_lines(self, lines: list[str]) -> str:
        return "\n".join(f"- {self._compact_line(line)}" for line in lines if line)

    def _compact_line(self, text: str, *, limit: int = 220) -> str:
        compact = re.sub(r"\s+", " ", text.strip(" \t\r\n-・"))
        if len(compact) <= limit:
            return compact
        return compact[: limit - 1].rstrip() + "…"

    def _contains_any(self, text: str, terms: tuple[str, ...]) -> bool:
        lower = text.lower()
        return any(term.lower() in lower for term in terms)

    def _last_answer_context(self, session: ChatSession) -> dict | None:
        answer_index = -1
        answer_message: StoredMessage | None = None
        for index in range(len(session.messages) - 1, -1, -1):
            message = session.messages[index]
            if (
                message.role == "assistant"
                and message.ai_action == "answer_with_citations"
                and message.citations
            ):
                answer_index = index
                answer_message = message
                break
        if answer_message is None:
            return None

        previous_question = ""
        for message in reversed(session.messages[:answer_index]):
            if message.role == "user":
                previous_question = message.content_redacted
                break

        document_ids = [
            str(citation.get("document_id") or "")
            for citation in answer_message.citations
            if citation.get("document_id")
        ]
        return {
            "question": previous_question,
            "answer": answer_message.content_redacted,
            "document_ids": list(dict.fromkeys(document_ids)),
        }

    def _create_handoff(
        self, session: ChatSession, *, reason: str, comment: str, priority: str = "normal"
    ) -> dict:
        if session.handoff_package_id:
            existing = self._handoffs.get((session.tenant_id, session.handoff_package_id))
            if existing:
                return existing
        handoff_id = _id("handoff")
        package = {
            "handoff_package_id": handoff_id,
            "session_id": session.session_id,
            "status": "queued",
            "reason": reason,
            "priority": priority,
            "summary": self._summary(session),
            "collected_slots": dict(session.collected_slots),
            "missing_slots": list(session.missing_slots),
            "rag_citations": list((session.last_rag or {}).get("citations") or []),
            "recommended_action": "会話履歴と根拠不足理由を確認してください。",
            "comment_redacted": _redact(comment),
            "transcript": [m.public() for m in session.messages],
            "created_at": _now(),
        }
        self._handoffs[(session.tenant_id, handoff_id)] = package
        session.handoff_required = True
        session.handoff_package_id = handoff_id
        session.status = "handoff_pending"
        return package

    def _create_ticket(self, session: ChatSession) -> dict:
        digest = hashlib.sha256(
            f"{session.tenant_id}:{session.session_id}:cancel".encode("utf-8")
        ).hexdigest()[:10]
        ticket = {
            "ticket_id": f"ticket_{digest}",
            "status": "created",
            "idempotency_key": f"{session.session_id}:cancel_subscription",
            "created_at": _now(),
        }
        session.ticket = ticket
        return ticket

    def _filter_chatbot_citations(
        self, session: ChatSession, citations: list[dict], collection_id: str | None
    ) -> tuple[list[dict], list[str]]:
        allowed: list[dict] = []
        policy_ids: list[str] = []
        for citation in citations:
            policy = self._matching_source_policy(session, citation, collection_id)
            if policy:
                allowed.append(citation)
                policy_ids.append(str(policy["policy_id"]))
        return allowed, sorted(set(policy_ids))

    def _pre_rag_source_policy_ids(
        self, session: ChatSession, collection_id: str | None
    ) -> list[str]:
        """Return collection-wide policies that can be enforced before the current RAG adapter.

        P0 can only pass a collection scope to the existing answer contract. Source-specific policies
        therefore fail closed before retrieval to avoid generating text from mixed allowed/blocked
        sources and merely hiding blocked citations afterwards.
        """
        policy_ids: list[str] = []
        for policy in self._source_policy_repo.list(session.tenant_id):
            if policy.get("status") != "active":
                continue
            if str(policy.get("source_id") or ""):
                continue
            policy_collection = str(policy.get("collection_id") or "")
            if not collection_id or not policy_collection or policy_collection != collection_id:
                continue
            if self._policy_allows_turn(policy, session):
                policy_ids.append(str(policy["policy_id"]))
        return sorted(set(policy_ids))

    def _matching_source_policy(
        self, session: ChatSession, citation: dict, collection_id: str | None
    ) -> dict | None:
        source_id = str(citation.get("source_id") or "")
        candidates = [
            policy
            for policy in self._source_policy_repo.list(session.tenant_id)
            if policy.get("status") == "active"
        ]
        for policy in candidates:
            policy_source = str(policy.get("source_id") or "")
            policy_collection = str(policy.get("collection_id") or "")
            if policy_source and policy_source != source_id:
                continue
            if policy_collection and (not collection_id or policy_collection != collection_id):
                continue
            if not self._policy_allows_turn(policy, session):
                continue
            return policy
        return None

    def _policy_allows_turn(self, policy: dict, session: ChatSession) -> bool:
        mode = str(policy.get("exposure_mode") or "disabled")
        if mode == "disabled":
            return False
        if session.channel == "web_chat" and mode not in {
            "internal_authenticated",
            "external_authenticated",
        }:
            return False
        if session.channel == "public_widget" and mode not in {
            "external_authenticated",
            "external_anonymous",
        }:
            return False
        if session.channel == "public_widget":
            allowed_origins = {
                _origin(str(domain)) for domain in (policy.get("allowed_domains") or [])
            }
            if (
                not allowed_origins
                or _origin(str(session.metadata.get("widget_origin") or "")) not in allowed_origins
            ):
                return False
            if mode == "external_anonymous" and not policy.get("required_document_tags"):
                return False
        channels = set(str(x) for x in (policy.get("allowed_channels") or []))
        if channels and session.channel not in channels:
            return False
        intents = set(str(x) for x in (policy.get("allowed_intents") or []))
        if intents and session.current_intent and not self._policy_intent_allows_rag_turn(
            intents, session.current_intent
        ):
            return False
        scenarios = set(str(x) for x in (policy.get("allowed_scenario_ids") or []))
        if scenarios and session.scenario_id and session.scenario_id not in scenarios:
            return False
        return True

    def _policy_intent_allows_rag_turn(self, allowed_intents: set[str], current_intent: str) -> bool:
        if current_intent in allowed_intents:
            return True
        non_rag_intents = {"cancel_subscription", "confirm", "human_handoff", "high_risk"}
        return "rag_question" in allowed_intents and current_intent not in non_rag_intents

    def _classify_intent(self, text: str, current: str | None) -> str:
        normalized = text.lower()
        if self._is_confirmation(text):
            return "confirm"
        if any(
            word in normalized for word in ("人間", "担当者", "オペレーター", "human", "operator")
        ):
            return "human_handoff"
        if any(
            word in normalized
            for word in ("返金保証", "補償", "訴訟", "法的", "損害賠償", "medical", "legal")
        ):
            return "high_risk"
        if any(word in normalized for word in ("解約", "キャンセル", "退会", "cancel")):
            return "cancel_subscription"
        if any(word in normalized for word in ("料金", "価格", "費用", "pricing", "price")):
            return "pricing_question"
        return current or "rag_question"

    def _extract_slots(self, text: str, existing: dict[str, str]) -> dict[str, str]:
        slots: dict[str, str] = {}
        email = EMAIL_RE.search(text)
        if email:
            slots["email"] = _redact(email.group(1))
        if "company_name" not in existing:
            patterns = [
                r"(?:会社名|会社|契約者名|法人名)\s*(?:は|:|：)?\s*([^\n。]+)",
                r"([A-Za-z0-9一-龥ぁ-んァ-ンー・]+(?:株式会社|合同会社|有限会社|Inc\.?|Ltd\.?))",
            ]
            for pattern in patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    candidate = match.group(1).strip()
                    if candidate and "@" not in candidate:
                        slots["company_name"] = _redact(candidate)
                        break
        return slots

    def _is_confirmation(self, text: str) -> bool:
        normalized = text.strip().lower()
        return normalized in {"confirm", "ok", "yes", "はい", "進める", "お願いします", "作成する"}

    def _summary(self, session: ChatSession) -> str:
        user_turns = [m.content_redacted for m in session.messages if m.role == "user"]
        if not user_turns:
            return ""
        latest = user_turns[-3:]
        return " / ".join(latest)

    def _require_session(self, principal: IdentityClaims, session_id: str) -> ChatSession:
        session = self._sessions.get((principal.tenant_id, session_id))
        if not session or not self._can_read_session(principal, session):
            raise KeyError("session")
        return session

    def _can_read_session(self, principal: IdentityClaims, session: ChatSession) -> bool:
        if principal.tenant_id != session.tenant_id:
            return False
        if principal.user_id == session.user_id:
            return True
        return bool({"operator", "ops_owner", "tenant_admin", "reviewer"} & set(principal.roles))

    def _has_any_role(self, principal: IdentityClaims, roles: set[str]) -> bool:
        return bool(set(principal.roles) & roles)

    def _tenant_scenario(self, tenant_id: str, scenario_id: str) -> ChatScenario | None:
        scenario = self._scenarios.get((tenant_id, scenario_id))
        if scenario:
            return scenario
        base = self._scenarios.get(("*", scenario_id))
        if not base:
            return None
        copy = ChatScenario(
            scenario_id=base.scenario_id,
            name=base.name,
            intents=list(base.intents),
            status=base.status,
            active_version_id=base.active_version_id,
            versions={
                version_id: ScenarioVersion(
                    version_id=version.version_id,
                    status=version.status,
                    required_slots=list(version.required_slots),
                    optional_slots=list(version.optional_slots),
                    steps=[dict(step) for step in version.steps],
                    validation_rules=[dict(rule) for rule in version.validation_rules],
                    rag_policy=dict(version.rag_policy),
                    actions=[dict(action) for action in version.actions],
                    response_templates=dict(version.response_templates),
                    handoff_conditions=[
                        dict(condition) for condition in version.handoff_conditions
                    ],
                    updated_at=version.updated_at,
                    approved_by=version.approved_by,
                    approved_at=version.approved_at,
                    published_by=version.published_by,
                    published_at=version.published_at,
                )
                for version_id, version in base.versions.items()
            },
        )
        self._scenarios[(tenant_id, scenario_id)] = copy
        return copy

    def _scenario_for_session(self, session: ChatSession) -> ChatScenario | None:
        if not session.scenario_id:
            return None
        return self._scenarios.get((session.tenant_id, session.scenario_id)) or self._scenarios.get(
            ("*", session.scenario_id)
        )

    def _required_slots_from_definition(
        self, body: dict, *, fallback: list[str] | None = None
    ) -> list[str]:
        if body.get("required_slots"):
            return [str(slot) for slot in body.get("required_slots") or []]
        required: list[str] = []
        for step in body.get("steps") or []:
            for slot in dict(step).get("required_slots") or []:
                slot_id = str(slot)
                if slot_id not in required:
                    required.append(slot_id)
        if required:
            return required
        return list(fallback or [])

    def _seed_scenarios(self) -> None:
        self._scenarios[("*", "cancel-basic")] = ChatScenario(
            scenario_id="cancel-basic",
            name="解約受付",
            intents=["cancel_subscription"],
            status="published",
            active_version_id="csv_cancel_basic_v1",
            versions={
                "csv_cancel_basic_v1": ScenarioVersion(
                    version_id="csv_cancel_basic_v1",
                    status="published",
                    required_slots=["email", "company_name"],
                    steps=[
                        {"id": "identify_customer", "required_slots": ["email", "company_name"]},
                        {"id": "confirm_final", "required_slots": ["final_confirmation"]},
                        {"id": "create_ticket", "action": "create_cancel_ticket"},
                    ],
                    handoff_conditions=[
                        {"reason": "customer_requested_human", "enabled": True},
                        {"reason": "insufficient_evidence", "enabled": True},
                    ],
                    approved_by="seed",
                    approved_at=_now(),
                    published_by="seed",
                    published_at=_now(),
                )
            },
        )
