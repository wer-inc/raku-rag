"""ChatBot persistence adapters.

Sprint1 S1-3: sessions / handoffs / feedback / scenarios are restart-durable behind
payload-JSONB repositories (same pattern as `raku_rag.persistence.phone_models`, proven live).
Repositories speak plain payload DICTS — (de)serialization lives on the chatbot dataclasses
(`to_payload`/`from_payload`) so this module never imports the service (no cycle).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Mapping, Protocol


class ChatbotSourcePolicyRepository(Protocol):
    def list(self, tenant_id: str) -> list[dict]: ...

    def upsert(self, tenant_id: str, policy_id: str, policy: Mapping[str, object]) -> dict: ...


@dataclass
class InMemoryChatbotSourcePolicyRepository:
    _items: dict[tuple[str, str], dict] = field(default_factory=dict)

    def list(self, tenant_id: str) -> list[dict]:
        policies = [
            dict(policy)
            for (stored_tenant, _), policy in self._items.items()
            if stored_tenant == tenant_id
        ]
        return sorted(policies, key=lambda policy: str(policy.get("policy_id") or ""))

    def upsert(self, tenant_id: str, policy_id: str, policy: Mapping[str, object]) -> dict:
        saved = dict(policy)
        saved["tenant_id"] = tenant_id
        saved["policy_id"] = policy_id
        self._items[(tenant_id, policy_id)] = saved
        return dict(saved)


class PostgresChatbotSourcePolicyRepository:
    _columns = (
        "policy_id",
        "tenant_id",
        "source_id",
        "collection_id",
        "exposure_mode",
        "allowed_channels",
        "allowed_scenario_ids",
        "allowed_intents",
        "required_document_tags",
        "blocked_document_tags",
        "require_approved_effective",
        "allow_obsolete_primary_evidence",
        "allowed_domains",
        "status",
        "unsupported_reason",
        "updated_by",
        "created_at",
        "updated_at",
    )

    def __init__(self, conn) -> None:
        self._conn = conn

    def list(self, tenant_id: str) -> list[dict]:
        from raku_rag.persistence.postgres import _use_tenant

        _use_tenant(self._conn, tenant_id)
        columns = ", ".join(self._columns)
        with self._conn.cursor() as cur:
            cur.execute(
                f"SELECT {columns} FROM chatbot_source_exposure_policies "
                "WHERE tenant_id = %s ORDER BY updated_at DESC, policy_id",
                (tenant_id,),
            )
            return [self._row_to_policy(row) for row in cur.fetchall()]

    def upsert(self, tenant_id: str, policy_id: str, policy: Mapping[str, object]) -> dict:
        from raku_rag.persistence.postgres import _use_tenant

        _use_tenant(self._conn, tenant_id)
        with self._conn.cursor() as cur:
            cur.execute(
                "INSERT INTO tenants (tenant_id) VALUES (%s) ON CONFLICT DO NOTHING",
                (tenant_id,),
            )
            columns = ", ".join(self._columns)
            cur.execute(
                "INSERT INTO chatbot_source_exposure_policies "
                "(tenant_id, policy_id, source_id, collection_id, exposure_mode, "
                "allowed_channels, allowed_scenario_ids, allowed_intents, "
                "required_document_tags, blocked_document_tags, require_approved_effective, "
                "allow_obsolete_primary_evidence, allowed_domains, status, unsupported_reason, "
                "updated_by) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (tenant_id, policy_id) DO UPDATE SET "
                "source_id=EXCLUDED.source_id, collection_id=EXCLUDED.collection_id, "
                "exposure_mode=EXCLUDED.exposure_mode, "
                "allowed_channels=EXCLUDED.allowed_channels, "
                "allowed_scenario_ids=EXCLUDED.allowed_scenario_ids, "
                "allowed_intents=EXCLUDED.allowed_intents, "
                "required_document_tags=EXCLUDED.required_document_tags, "
                "blocked_document_tags=EXCLUDED.blocked_document_tags, "
                "require_approved_effective=EXCLUDED.require_approved_effective, "
                "allow_obsolete_primary_evidence=EXCLUDED.allow_obsolete_primary_evidence, "
                "allowed_domains=EXCLUDED.allowed_domains, status=EXCLUDED.status, "
                "unsupported_reason=EXCLUDED.unsupported_reason, updated_by=EXCLUDED.updated_by, "
                "updated_at=now() "
                f"RETURNING {columns}",
                (
                    tenant_id,
                    policy_id,
                    str(policy.get("source_id") or ""),
                    str(policy.get("collection_id") or ""),
                    str(policy.get("exposure_mode") or "disabled"),
                    _text_list(policy.get("allowed_channels")),
                    _text_list(policy.get("allowed_scenario_ids")),
                    _text_list(policy.get("allowed_intents")),
                    _text_list(policy.get("required_document_tags")),
                    _text_list(policy.get("blocked_document_tags")),
                    bool(policy.get("require_approved_effective", True)),
                    bool(policy.get("allow_obsolete_primary_evidence", False)),
                    _text_list(policy.get("allowed_domains")),
                    str(policy.get("status") or "active"),
                    str(policy.get("unsupported_reason") or ""),
                    str(policy.get("updated_by") or ""),
                ),
            )
            row = cur.fetchone()
        return self._row_to_policy(row)

    def _row_to_policy(self, row) -> dict:
        from raku_rag.persistence.postgres import _iso

        data = dict(zip(self._columns, row))
        for key in (
            "allowed_channels",
            "allowed_scenario_ids",
            "allowed_intents",
            "required_document_tags",
            "blocked_document_tags",
            "allowed_domains",
        ):
            data[key] = list(data.get(key) or [])
        for key in ("created_at", "updated_at"):
            data[key] = _iso(data.get(key))
        if not data.get("unsupported_reason"):
            data.pop("unsupported_reason", None)
        return data


def _text_list(value: object) -> list[str]:
    if not isinstance(value, (list, tuple, set)):
        return []
    return [str(item) for item in value if item is not None]


# --- Sprint1 S1-3: session / handoff / feedback / scenario repositories -------------------------


class ChatSessionRepository(Protocol):
    def save(self, tenant_id: str, session_id: str, payload: Mapping[str, object]) -> None: ...

    def get(self, tenant_id: str, session_id: str) -> dict | None: ...

    def list(self, tenant_id: str) -> list[dict]: ...


class ChatHandoffRepository(Protocol):
    def save(self, tenant_id: str, handoff_id: str, package: Mapping[str, object]) -> None: ...

    def get(self, tenant_id: str, handoff_id: str) -> dict | None: ...


class ChatFeedbackRepository(Protocol):
    def save(self, tenant_id: str, evaluation_id: str, item: Mapping[str, object]) -> None: ...

    def list(self, tenant_id: str) -> list[dict]: ...


class ChatScenarioRepository(Protocol):
    def save(self, tenant_id: str, scenario_id: str, payload: Mapping[str, object]) -> None: ...

    def get(self, tenant_id: str, scenario_id: str) -> dict | None: ...

    def list(self, tenant_id: str) -> list[dict]: ...


@dataclass
class InMemoryChatSessionRepository:
    _items: dict[tuple[str, str], dict] = field(default_factory=dict)

    def save(self, tenant_id: str, session_id: str, payload: Mapping[str, object]) -> None:
        self._items[(tenant_id, session_id)] = dict(payload)

    def get(self, tenant_id: str, session_id: str) -> dict | None:
        payload = self._items.get((tenant_id, session_id))
        return dict(payload) if payload else None

    def list(self, tenant_id: str) -> list[dict]:
        return [
            dict(payload)
            for (stored_tenant, _), payload in self._items.items()
            if stored_tenant == tenant_id
        ]


@dataclass
class InMemoryChatHandoffRepository:
    _items: dict[tuple[str, str], dict] = field(default_factory=dict)

    def save(self, tenant_id: str, handoff_id: str, package: Mapping[str, object]) -> None:
        self._items[(tenant_id, handoff_id)] = dict(package)

    def get(self, tenant_id: str, handoff_id: str) -> dict | None:
        package = self._items.get((tenant_id, handoff_id))
        return dict(package) if package else None


@dataclass
class InMemoryChatFeedbackRepository:
    _items: dict[tuple[str, str], dict] = field(default_factory=dict)

    def save(self, tenant_id: str, evaluation_id: str, item: Mapping[str, object]) -> None:
        self._items[(tenant_id, evaluation_id)] = dict(item)

    def list(self, tenant_id: str) -> list[dict]:
        return [
            dict(item)
            for (stored_tenant, _), item in self._items.items()
            if stored_tenant == tenant_id
        ]


@dataclass
class InMemoryChatScenarioRepository:
    _items: dict[tuple[str, str], dict] = field(default_factory=dict)

    def save(self, tenant_id: str, scenario_id: str, payload: Mapping[str, object]) -> None:
        self._items[(tenant_id, scenario_id)] = dict(payload)

    def get(self, tenant_id: str, scenario_id: str) -> dict | None:
        payload = self._items.get((tenant_id, scenario_id))
        return dict(payload) if payload else None

    def list(self, tenant_id: str) -> list[dict]:
        return [
            dict(payload)
            for (stored_tenant, _), payload in self._items.items()
            if stored_tenant == tenant_id
        ]


def _payload_dict(value: object) -> dict:
    if isinstance(value, str):
        return json.loads(value)
    return dict(value) if isinstance(value, dict) else {}


class PostgresChatSessionRepository:
    """chatbot_sessions (0018): payload JSONB + typed columns for listing; RLS-forced."""

    def __init__(self, conn) -> None:
        self._conn = conn

    def save(self, tenant_id: str, session_id: str, payload: Mapping[str, object]) -> None:
        from raku_rag.persistence.postgres import _use_tenant

        _use_tenant(self._conn, tenant_id)
        data = dict(payload)
        with self._conn.cursor() as cur:
            cur.execute(
                "INSERT INTO tenants (tenant_id) VALUES (%s) ON CONFLICT DO NOTHING",
                (tenant_id,),
            )
            cur.execute(
                "INSERT INTO chatbot_sessions "
                "(tenant_id, session_id, user_id, channel, status, current_intent, "
                " last_message_at, payload) "
                "VALUES (%s,%s,%s,%s,%s,%s, COALESCE(%s::timestamptz, now()), %s) "
                "ON CONFLICT (tenant_id, session_id) DO UPDATE SET "
                "user_id=EXCLUDED.user_id, channel=EXCLUDED.channel, status=EXCLUDED.status, "
                "current_intent=EXCLUDED.current_intent, "
                "last_message_at=EXCLUDED.last_message_at, payload=EXCLUDED.payload, "
                "updated_at=now()",
                (
                    tenant_id,
                    session_id,
                    str(data.get("user_id") or ""),
                    str(data.get("channel") or "web_chat"),
                    str(data.get("status") or "active"),
                    str(data.get("current_intent") or ""),
                    str(data.get("last_message_at") or "") or None,
                    json.dumps(data),
                ),
            )

    def get(self, tenant_id: str, session_id: str) -> dict | None:
        from raku_rag.persistence.postgres import _use_tenant

        _use_tenant(self._conn, tenant_id)
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT payload FROM chatbot_sessions " "WHERE tenant_id = %s AND session_id = %s",
                (tenant_id, session_id),
            )
            row = cur.fetchone()
        return _payload_dict(row[0]) if row else None

    def list(self, tenant_id: str) -> list[dict]:
        from raku_rag.persistence.postgres import _use_tenant

        _use_tenant(self._conn, tenant_id)
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT payload FROM chatbot_sessions "
                "WHERE tenant_id = %s ORDER BY last_message_at DESC",
                (tenant_id,),
            )
            return [_payload_dict(row[0]) for row in cur.fetchall()]


class PostgresChatHandoffRepository:
    def __init__(self, conn) -> None:
        self._conn = conn

    def save(self, tenant_id: str, handoff_id: str, package: Mapping[str, object]) -> None:
        from raku_rag.persistence.postgres import _use_tenant

        _use_tenant(self._conn, tenant_id)
        data = dict(package)
        with self._conn.cursor() as cur:
            cur.execute(
                "INSERT INTO tenants (tenant_id) VALUES (%s) ON CONFLICT DO NOTHING",
                (tenant_id,),
            )
            cur.execute(
                "INSERT INTO chatbot_handoffs "
                "(tenant_id, handoff_id, session_id, status, reason, payload) "
                "VALUES (%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (tenant_id, handoff_id) DO UPDATE SET "
                "status=EXCLUDED.status, reason=EXCLUDED.reason, payload=EXCLUDED.payload",
                (
                    tenant_id,
                    handoff_id,
                    str(data.get("session_id") or ""),
                    str(data.get("status") or "queued"),
                    str(data.get("reason") or ""),
                    json.dumps(data),
                ),
            )

    def get(self, tenant_id: str, handoff_id: str) -> dict | None:
        from raku_rag.persistence.postgres import _use_tenant

        _use_tenant(self._conn, tenant_id)
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT payload FROM chatbot_handoffs " "WHERE tenant_id = %s AND handoff_id = %s",
                (tenant_id, handoff_id),
            )
            row = cur.fetchone()
        return _payload_dict(row[0]) if row else None


class PostgresChatFeedbackRepository:
    def __init__(self, conn) -> None:
        self._conn = conn

    def save(self, tenant_id: str, evaluation_id: str, item: Mapping[str, object]) -> None:
        from raku_rag.persistence.postgres import _use_tenant

        _use_tenant(self._conn, tenant_id)
        data = dict(item)
        with self._conn.cursor() as cur:
            cur.execute(
                "INSERT INTO tenants (tenant_id) VALUES (%s) ON CONFLICT DO NOTHING",
                (tenant_id,),
            )
            cur.execute(
                "INSERT INTO chatbot_feedback "
                "(tenant_id, evaluation_id, session_id, payload) "
                "VALUES (%s,%s,%s,%s) "
                "ON CONFLICT (tenant_id, evaluation_id) DO UPDATE SET payload=EXCLUDED.payload",
                (
                    tenant_id,
                    evaluation_id,
                    str(data.get("session_id") or ""),
                    json.dumps(data),
                ),
            )

    def list(self, tenant_id: str) -> list[dict]:
        from raku_rag.persistence.postgres import _use_tenant

        _use_tenant(self._conn, tenant_id)
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT payload FROM chatbot_feedback WHERE tenant_id = %s ORDER BY created_at",
                (tenant_id,),
            )
            return [_payload_dict(row[0]) for row in cur.fetchall()]


class PostgresChatScenarioRepository:
    def __init__(self, conn) -> None:
        self._conn = conn

    def save(self, tenant_id: str, scenario_id: str, payload: Mapping[str, object]) -> None:
        from raku_rag.persistence.postgres import _use_tenant

        _use_tenant(self._conn, tenant_id)
        data = dict(payload)
        with self._conn.cursor() as cur:
            cur.execute(
                "INSERT INTO tenants (tenant_id) VALUES (%s) ON CONFLICT DO NOTHING",
                (tenant_id,),
            )
            cur.execute(
                "INSERT INTO chatbot_scenarios (tenant_id, scenario_id, status, payload) "
                "VALUES (%s,%s,%s,%s) "
                "ON CONFLICT (tenant_id, scenario_id) DO UPDATE SET "
                "status=EXCLUDED.status, payload=EXCLUDED.payload, updated_at=now()",
                (
                    tenant_id,
                    scenario_id,
                    str(data.get("status") or "draft"),
                    json.dumps(data),
                ),
            )

    def get(self, tenant_id: str, scenario_id: str) -> dict | None:
        from raku_rag.persistence.postgres import _use_tenant

        _use_tenant(self._conn, tenant_id)
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT payload FROM chatbot_scenarios "
                "WHERE tenant_id = %s AND scenario_id = %s",
                (tenant_id, scenario_id),
            )
            row = cur.fetchone()
        return _payload_dict(row[0]) if row else None

    def list(self, tenant_id: str) -> list[dict]:
        from raku_rag.persistence.postgres import _use_tenant

        _use_tenant(self._conn, tenant_id)
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT payload FROM chatbot_scenarios "
                "WHERE tenant_id = %s ORDER BY scenario_id",
                (tenant_id,),
            )
            return [_payload_dict(row[0]) for row in cur.fetchall()]
