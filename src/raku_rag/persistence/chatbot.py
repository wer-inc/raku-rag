"""ChatBot persistence adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Protocol


class ChatbotSourcePolicyRepository(Protocol):
    def list(self, tenant_id: str) -> list[dict]: ...

    def upsert(
        self, tenant_id: str, policy_id: str, policy: Mapping[str, object]
    ) -> dict: ...


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

    def upsert(
        self, tenant_id: str, policy_id: str, policy: Mapping[str, object]
    ) -> dict:
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

    def upsert(
        self, tenant_id: str, policy_id: str, policy: Mapping[str, object]
    ) -> dict:
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
