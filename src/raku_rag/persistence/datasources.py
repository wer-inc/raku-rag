"""Datasource configuration repositories.

The public datasource record is safe to return to the product API: credentials are stored behind a
secret reference and merged back into connector config only inside trusted sync execution.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass, field
from typing import Mapping, Protocol

from raku_rag.persistence.secret_store import SecretNotFoundError, SecretStore
from raku_rag.workers.ingestion import _now

_SECRET_CONFIG_KEYS = {
    "access_token",
    "api_key",
    "api_secret",
    "api_token",
    "connection_string",
    "developer_token",
    "dsn",
    "integration_token",
    "oauth_token",
    "password",
    "secret",
    "secret_access_key",
    "secret_key",
    "token",
}


@dataclass
class DataSourceRecord:
    source_id: str
    tenant_id: str
    collection_id: str
    type: str
    config: dict = field(default_factory=dict)
    sync_schedule: str | None = None
    last_synced_at: str | None = None
    status: str = "active"
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    def to_public_dict(self) -> dict:
        config = copy.deepcopy(self.config)
        if config.get("credential_ref"):
            config["credential_status"] = "configured"
        return {
            "source_id": self.source_id,
            "tenant_id": self.tenant_id,
            "collection_id": self.collection_id,
            "type": self.type,
            "config": config,
            "sync_schedule": self.sync_schedule,
            "last_synced_at": self.last_synced_at,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class DataSourceRepository(Protocol):
    def list(self, tenant_id: str, *, collection_id: str = "") -> list[dict]: ...

    def get(self, tenant_id: str, source_id: str) -> dict | None: ...

    def upsert(
        self, tenant_id: str, source_id: str, body: Mapping[str, object], *, actor: str = ""
    ) -> dict: ...

    def list_scheduled(self) -> list[dict]:
        """S2-1 scheduler bootstrap: [{tenant_id, source_id, sync_schedule}] across tenants.

        Metadata only (never config/credentials). The Postgres impl reads
        `sync_schedule_registry` under the dedicated `app.sync_scheduler` GUC (the policy's
        explicit read escape — see the 0019 migration header); consumers MUST re-resolve each
        entry through the RLS-checked `get()` before acting on it.
        """
        ...


@dataclass
class InMemoryDataSourceRepository:
    secret_store: SecretStore
    _items: dict[tuple[str, str], DataSourceRecord] = field(default_factory=dict)

    def list(self, tenant_id: str, *, collection_id: str = "") -> list[dict]:
        records = [record for (t, _), record in self._items.items() if t == tenant_id]
        if collection_id:
            records = [record for record in records if record.collection_id == collection_id]
        records.sort(key=lambda record: record.updated_at, reverse=True)
        return [record.to_public_dict() for record in records]

    def get(self, tenant_id: str, source_id: str) -> dict | None:
        record = self._items.get((tenant_id, source_id))
        return record.to_public_dict() if record else None

    def list_scheduled(self) -> list[dict]:
        return [
            {"tenant_id": t, "source_id": s, "sync_schedule": record.sync_schedule or ""}
            for (t, s), record in self._items.items()
            if (record.sync_schedule or "").strip()
        ]

    def upsert(
        self, tenant_id: str, source_id: str, body: Mapping[str, object], *, actor: str = ""
    ) -> dict:
        existing = self._items.get((tenant_id, source_id))
        clean = _clean_body(
            tenant_id, source_id, body, self.secret_store, existing.config if existing else {}
        )
        now = _now()
        record = DataSourceRecord(
            source_id=source_id,
            tenant_id=tenant_id,
            collection_id=str(
                clean.get("collection_id") or (existing.collection_id if existing else "default")
            ),
            type=str(clean.get("type") or (existing.type if existing else "upload")),
            config=clean["config"],
            sync_schedule=_optional_str(
                clean.get("sync_schedule"), existing.sync_schedule if existing else None
            ),
            last_synced_at=existing.last_synced_at if existing else None,
            status=str(clean.get("status") or (existing.status if existing else "active")),
            created_at=existing.created_at if existing else now,
            updated_at=now,
        )
        self._items[(tenant_id, source_id)] = record
        return record.to_public_dict()


class PostgresDataSourceRepository:
    def __init__(self, conn, secret_store: SecretStore) -> None:
        self._conn = conn
        self._secret_store = secret_store

    def list(self, tenant_id: str, *, collection_id: str = "") -> list[dict]:
        from raku_rag.persistence.postgres import _use_tenant

        _use_tenant(self._conn, tenant_id)
        clauses = ["tenant_id = %s"]
        params: list[object] = [tenant_id]
        if collection_id:
            clauses.append("collection_id = %s")
            params.append(collection_id)
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT source_id, tenant_id, collection_id, type, config, sync_schedule, "
                "last_synced_at, status, created_at, updated_at FROM data_sources "
                "WHERE " + " AND ".join(clauses) + " ORDER BY updated_at DESC",
                params,
            )
            return [_row_to_record(row).to_public_dict() for row in cur.fetchall()]

    def get(self, tenant_id: str, source_id: str) -> dict | None:
        from raku_rag.persistence.postgres import _use_tenant

        _use_tenant(self._conn, tenant_id)
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT source_id, tenant_id, collection_id, type, config, sync_schedule, "
                "last_synced_at, status, created_at, updated_at FROM data_sources "
                "WHERE tenant_id = %s AND source_id = %s",
                (tenant_id, source_id),
            )
            row = cur.fetchone()
        return _row_to_record(row).to_public_dict() if row else None

    def upsert(
        self, tenant_id: str, source_id: str, body: Mapping[str, object], *, actor: str = ""
    ) -> dict:
        from raku_rag.persistence.postgres import Json, _ensure_collection_parent, _use_tenant

        existing = self.get(tenant_id, source_id)
        existing_config = existing.get("config", {}) if existing else {}
        clean = _clean_body(tenant_id, source_id, body, self._secret_store, existing_config)
        collection_id = str(
            clean.get("collection_id") or (existing or {}).get("collection_id") or "default"
        )
        _use_tenant(self._conn, tenant_id)
        _ensure_collection_parent(self._conn, tenant_id, collection_id)
        with self._conn.cursor() as cur:
            cur.execute(
                "INSERT INTO data_sources "
                "(source_id, tenant_id, collection_id, type, config, sync_schedule, status) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (tenant_id, source_id) DO UPDATE SET "
                "collection_id=EXCLUDED.collection_id, type=EXCLUDED.type, config=EXCLUDED.config, "
                "sync_schedule=EXCLUDED.sync_schedule, status=EXCLUDED.status, updated_at=now()",
                (
                    source_id,
                    tenant_id,
                    collection_id,
                    str(clean.get("type") or (existing or {}).get("type") or "upload"),
                    Json(clean["config"]),
                    _optional_str(
                        clean.get("sync_schedule"), (existing or {}).get("sync_schedule")
                    ),
                    str(clean.get("status") or (existing or {}).get("status") or "active"),
                ),
            )
            # S2-1: mirror scheduling metadata into the scheduler bootstrap registry (0019).
            schedule_value = (
                _optional_str(clean.get("sync_schedule"), (existing or {}).get("sync_schedule"))
                or ""
            ).strip()
            if schedule_value:
                cur.execute(
                    "INSERT INTO sync_schedule_registry (tenant_id, source_id, sync_schedule) "
                    "VALUES (%s,%s,%s) "
                    "ON CONFLICT (tenant_id, source_id) DO UPDATE SET "
                    "sync_schedule=EXCLUDED.sync_schedule, updated_at=now()",
                    (tenant_id, source_id, schedule_value),
                )
            else:
                cur.execute(
                    "DELETE FROM sync_schedule_registry "
                    "WHERE tenant_id = %s AND source_id = %s",
                    (tenant_id, source_id),
                )
        saved = self.get(tenant_id, source_id)
        assert saved is not None
        return saved

    def list_scheduled(self) -> list[dict]:
        """Cross-tenant scheduling metadata via the registry's explicit scheduler read escape."""
        with self._conn.cursor() as cur:
            cur.execute("SELECT set_config('app.sync_scheduler', '1', false)")
            try:
                cur.execute(
                    "SELECT tenant_id, source_id, sync_schedule FROM sync_schedule_registry "
                    "WHERE sync_schedule <> '' ORDER BY tenant_id, source_id"
                )
                rows = cur.fetchall()
            finally:
                cur.execute("SELECT set_config('app.sync_scheduler', '', false)")
        return [
            {"tenant_id": row[0], "source_id": row[1], "sync_schedule": row[2]} for row in rows
        ]

    def remove_schedule(self, tenant_id: str, source_id: str) -> None:
        """Prune a stale registry row (datasource no longer resolves)."""
        from raku_rag.persistence.postgres import _use_tenant

        _use_tenant(self._conn, tenant_id)
        with self._conn.cursor() as cur:
            cur.execute(
                "DELETE FROM sync_schedule_registry WHERE tenant_id = %s AND source_id = %s",
                (tenant_id, source_id),
            )


def materialize_datasource_credentials(
    datasource: Mapping[str, object], secret_store: SecretStore
) -> dict:
    """Return a datasource copy with secret values merged into config for connector execution."""

    result = copy.deepcopy(dict(datasource))
    config = dict(result.get("config") or {})
    ref = str(config.get("credential_ref") or "")
    if ref:
        tenant_id = str(result.get("tenant_id") or "")
        credentials = _retrieve_credentials(secret_store, tenant_id, ref)
        config.update(credentials)
    result["config"] = config
    return result


def _row_to_record(row) -> DataSourceRecord:
    from raku_rag.persistence.postgres import _iso

    return DataSourceRecord(
        source_id=row[0],
        tenant_id=row[1],
        collection_id=row[2],
        type=row[3],
        config=dict(row[4] or {}),
        sync_schedule=row[5],
        last_synced_at=_iso(row[6]) if row[6] else None,
        status=row[7],
        created_at=_iso(row[8]),
        updated_at=_iso(row[9]),
    )


def _clean_body(
    tenant_id: str,
    source_id: str,
    body: Mapping[str, object],
    secret_store: SecretStore,
    existing_config: Mapping[str, object],
) -> dict:
    config = dict(existing_config or {})
    incoming_config = (
        dict(body.get("config") or {}) if isinstance(body.get("config"), Mapping) else {}
    )
    config.update(incoming_config)

    credentials: dict[str, object] = {}
    raw_credentials = body.get("credentials")
    if isinstance(raw_credentials, Mapping):
        credentials.update({str(k): v for k, v in raw_credentials.items() if v not in (None, "")})
    for key in list(config):
        if _is_secret_key(key):
            value = config.pop(key)
            if value not in (None, ""):
                credentials[key] = value

    if credentials:
        config["credential_ref"] = _store_credentials(
            secret_store, tenant_id, source_id, credentials
        )

    return {
        "collection_id": body.get("collection_id"),
        "type": body.get("type"),
        "config": config,
        "sync_schedule": body.get("sync_schedule"),
        "status": body.get("status"),
    }


def _is_secret_key(key: str) -> bool:
    normalized = key.strip().lower()
    return normalized in _SECRET_CONFIG_KEYS or normalized.endswith("_token")


def _store_credentials(
    secret_store: SecretStore,
    tenant_id: str,
    source_id: str,
    credentials: Mapping[str, object],
) -> str:
    ref = _secret_name(source_id)
    secret_store.store_secret(
        tenant_id,
        ref,
        json.dumps(dict(credentials), sort_keys=True, default=str),
    )
    return ref


def _retrieve_credentials(secret_store: SecretStore, tenant_id: str, ref: str) -> dict:
    try:
        raw = secret_store.retrieve_secret(tenant_id, ref)
    except SecretNotFoundError:
        return {}
    value = json.loads(raw or "{}")
    return value if isinstance(value, dict) else {}


def _secret_name(source_id: str) -> str:
    digest = hashlib.sha256(source_id.encode("utf-8")).hexdigest()[:16]
    safe_source = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in source_id)[:64]
    return f"datasources/{safe_source or 'source'}-{digest}"


def _optional_str(value: object, fallback: object = None) -> str | None:
    if value is None:
        value = fallback
    if value is None:
        return None
    return str(value)
