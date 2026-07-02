"""★V2 tenant_lexicon — per-tenant vocabulary/message overrides (0021, RLS-forced).

Follows the datasource/chatbot persistence precedent: every Postgres query runs after
``_use_tenant`` so RLS enforces isolation even if a WHERE clause is wrong.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field


@dataclass
class InMemoryLexiconRepository:
    _items: dict[tuple[str, str, str], tuple[str, ...]] = field(default_factory=dict)

    def get_namespace(self, tenant_id: str, namespace: str) -> dict[str, tuple[str, ...]]:
        return {
            key: values
            for (t, ns, key), values in self._items.items()
            if t == tenant_id and ns == namespace
        }

    def upsert(
        self, tenant_id: str, namespace: str, key: str, values: tuple[str, ...], updated_by: str
    ) -> None:
        self._items[(tenant_id, namespace, key)] = tuple(values)

    def delete(self, tenant_id: str, namespace: str, key: str) -> bool:
        return self._items.pop((tenant_id, namespace, key), None) is not None


class PostgresLexiconRepository:
    def __init__(self, conn) -> None:
        self._conn = conn

    def get_namespace(self, tenant_id: str, namespace: str) -> dict[str, tuple[str, ...]]:
        from raku_rag.persistence.postgres import _use_tenant

        _use_tenant(self._conn, tenant_id)
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT key, values FROM tenant_lexicon " "WHERE tenant_id = %s AND namespace = %s",
                (tenant_id, namespace),
            )
            rows = cur.fetchall()
        out: dict[str, tuple[str, ...]] = {}
        for key, values in rows:
            items = values if isinstance(values, list) else json.loads(values or "[]")
            out[str(key)] = tuple(str(v) for v in items)
        return out

    def upsert(
        self, tenant_id: str, namespace: str, key: str, values: tuple[str, ...], updated_by: str
    ) -> None:
        from raku_rag.persistence.postgres import _use_tenant

        _use_tenant(self._conn, tenant_id)
        with self._conn.cursor() as cur:
            cur.execute(
                "INSERT INTO tenants (tenant_id) VALUES (%s) ON CONFLICT DO NOTHING",
                (tenant_id,),
            )
            cur.execute(
                "INSERT INTO tenant_lexicon (tenant_id, namespace, key, values, updated_by) "
                "VALUES (%s,%s,%s,%s::jsonb,%s) "
                "ON CONFLICT (tenant_id, namespace, key) DO UPDATE SET "
                "values=EXCLUDED.values, updated_by=EXCLUDED.updated_by, updated_at=now()",
                (tenant_id, namespace, key, json.dumps(list(values)), updated_by),
            )

    def delete(self, tenant_id: str, namespace: str, key: str) -> bool:
        from raku_rag.persistence.postgres import _use_tenant

        _use_tenant(self._conn, tenant_id)
        with self._conn.cursor() as cur:
            cur.execute(
                "DELETE FROM tenant_lexicon WHERE tenant_id = %s AND namespace = %s AND key = %s",
                (tenant_id, namespace, key),
            )
            return cur.rowcount == 1
