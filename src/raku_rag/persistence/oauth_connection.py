"""Connector OAuth connections (021-gdrive-oauth).

An :class:`OAuthConnection` ties a tenant's datasource to a stored refresh token. The refresh token
itself lives in the :class:`~raku_rag.persistence.secret_store.SecretStore`; this record only holds a
``refresh_token_secret_ref`` (the SecretStore *name*, tenant supplied separately) — never the token.

Runtime storage is in-memory (mirrors the in-memory admin/datasource store): an answer-service
restart drops connections and the tenant re-connects. Postgres migration 0012 is the forward-looking
durable home and is NOT wired as the runtime source of truth in this PR.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Protocol


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def new_connection_id() -> str:
    """Opaque connection id. Random (not derived) so a tenant can connect multiple Drive accounts."""
    return uuid.uuid4().hex


def secret_ref_for(connection_id: str) -> str:
    """SecretStore name for a connection's refresh token. Tenant is applied by the store, so it is
    intentionally NOT part of this ref (avoids double-encoding the tenant in the physical secret id).
    """
    return f"gdrive/{connection_id}"


@dataclass(frozen=True)
class OAuthConnection:
    tenant_id: str
    connection_id: str
    source_id: str
    provider: str  # e.g. "google_drive"
    refresh_token_secret_ref: str
    scope: str = ""
    status: str = "connected"  # connected | revoked | error
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    def to_dict(self) -> dict:
        return {
            "tenant_id": self.tenant_id,
            "connection_id": self.connection_id,
            "source_id": self.source_id,
            "provider": self.provider,
            "refresh_token_secret_ref": self.refresh_token_secret_ref,
            "scope": self.scope,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


def build_connection(
    *,
    tenant_id: str,
    source_id: str,
    provider: str = "google_drive",
    scope: str = "",
    connection_id: str | None = None,
) -> OAuthConnection:
    """Create a new connection with a generated id and derived secret ref."""
    cid = connection_id or new_connection_id()
    return OAuthConnection(
        tenant_id=tenant_id,
        connection_id=cid,
        source_id=source_id,
        provider=provider,
        refresh_token_secret_ref=secret_ref_for(cid),
        scope=scope,
    )


class OAuthConnectionStore(Protocol):
    def get(self, tenant_id: str, connection_id: str) -> OAuthConnection | None: ...
    def get_by_source(self, tenant_id: str, source_id: str) -> OAuthConnection | None: ...
    def upsert(self, connection: OAuthConnection) -> OAuthConnection: ...
    def delete(self, tenant_id: str, connection_id: str) -> bool: ...


class InMemoryOAuthConnectionStore:
    """Tenant-scoped in-memory connection store (runtime source of truth this PR)."""

    def __init__(self) -> None:
        self._items: dict[tuple[str, str], OAuthConnection] = {}

    def get(self, tenant_id: str, connection_id: str) -> OAuthConnection | None:
        return self._items.get((tenant_id, connection_id))

    def get_by_source(self, tenant_id: str, source_id: str) -> OAuthConnection | None:
        # Most-recent wins if a source were re-connected.
        matches = [
            c for (t, _cid), c in self._items.items() if t == tenant_id and c.source_id == source_id
        ]
        if not matches:
            return None
        return max(matches, key=lambda c: c.updated_at)

    def upsert(self, connection: OAuthConnection) -> OAuthConnection:
        stored = replace(connection, updated_at=_now())
        self._items[(connection.tenant_id, connection.connection_id)] = stored
        return stored

    def delete(self, tenant_id: str, connection_id: str) -> bool:
        return self._items.pop((tenant_id, connection_id), None) is not None
