"""Postgres-backed manufacturing audit writer.

This mirrors ``InMemoryAuditLogWriter`` while storing the redacted, hash-chained canonical
``AuditLogEntry`` payload in the RLS-protected manufacturing audit table.
"""

from __future__ import annotations

import json
from dataclasses import fields, replace
from enum import Enum

from raku_rag.core.errors import TenantIsolationError
from raku_rag.core.tenancy import enforce_same_tenant
from raku_rag.domain.models import IdentityClaims
from raku_rag.manufacturing.domain.audit import (
    AuditLogEntry,
    compute_entry_hash,
    sanitize_audit_log_entry,
)
from raku_rag.manufacturing.domain.safety import SafetyBlockReason
from raku_rag.observability.redaction import Redactor
from raku_rag.persistence.postgres import _use_tenant


class PostgresManufacturingAuditLogWriter:
    """Durable, tenant-scoped manufacturing audit log with tamper-evident hash chain."""

    def __init__(self, conn, redactor: Redactor | None = None) -> None:
        self._conn = conn
        self._redactor = redactor or Redactor()

    def record(self, entry: AuditLogEntry) -> None:
        if not entry.tenant_id:
            raise TenantIsolationError("resource not found")
        safe = sanitize_audit_log_entry(entry, self._redactor)
        _use_tenant(self._conn, safe.tenant_id)
        prev_hash = self._latest_hash(safe.tenant_id)
        safe = replace(safe, prev_hash=prev_hash)
        safe.entry_hash = compute_entry_hash(safe)
        payload = _entry_to_payload(safe)
        with self._conn.cursor() as cur:
            cur.execute(
                "INSERT INTO manufacturing_audit_events (audit_event_id, tenant_id, actor_id, "
                "action, resource_type, resource_id, factory_id, department_id, decision, "
                "safety_block_reason, citation_ids, document_ids_used, prev_hash, entry_hash, "
                "created_at, entry_payload) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)",
                (
                    safe.log_id,
                    safe.tenant_id,
                    safe.actor_id or "",
                    safe.action,
                    safe.resource_type or "",
                    safe.resource_id or "",
                    safe.factory_id or "",
                    safe.department_id or "",
                    safe.decision or "",
                    _enum_value(safe.safety_block_reason),
                    list(safe.citation_ids),
                    list(safe.document_ids_used),
                    safe.prev_hash or "",
                    safe.entry_hash or "",
                    safe.timestamp,
                    json.dumps(payload, sort_keys=True),
                ),
            )

    def read_all(self, principal: IdentityClaims) -> tuple[AuditLogEntry, ...]:
        _use_tenant(self._conn, principal.tenant_id)
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT entry_payload FROM manufacturing_audit_events "
                "ORDER BY created_at ASC, audit_event_id ASC"
            )
            rows = cur.fetchall()
        return tuple(_entry_from_payload(row[0]) for row in rows if row[0])

    def read_for_tenant(
        self, principal: IdentityClaims, tenant_id: str
    ) -> tuple[AuditLogEntry, ...]:
        enforce_same_tenant(principal, resource_tenant_id=tenant_id)
        return self.read_all(principal)

    def verify_chain(self, principal: IdentityClaims) -> bool:
        prev: str | None = None
        for entry in self.read_all(principal):
            if entry.prev_hash != prev:
                return False
            if entry.entry_hash != compute_entry_hash(entry):
                return False
            prev = entry.entry_hash
        return True

    def _latest_hash(self, tenant_id: str) -> str | None:
        _use_tenant(self._conn, tenant_id)
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT entry_hash FROM manufacturing_audit_events "
                "ORDER BY created_at DESC, audit_event_id DESC LIMIT 1"
            )
            row = cur.fetchone()
        return (row[0] or None) if row else None


def _entry_to_payload(entry: AuditLogEntry) -> dict:
    payload = {}
    for field in fields(entry):
        payload[field.name] = _serialize_value(getattr(entry, field.name))
    return payload


def _entry_from_payload(payload: dict | str) -> AuditLogEntry:
    data = json.loads(payload) if isinstance(payload, str) else dict(payload)
    if data.get("safety_block_reason"):
        data["safety_block_reason"] = SafetyBlockReason(data["safety_block_reason"])
    for key in ("citation_ids", "document_ids_used"):
        data[key] = tuple(data.get(key) or ())
    return AuditLogEntry(**data)


def _serialize_value(value):
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, list):
        return [_serialize_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _serialize_value(child) for key, child in value.items()}
    return value


def _enum_value(value: object) -> str:
    return value.value if isinstance(value, Enum) else str(value or "")
