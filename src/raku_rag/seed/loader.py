"""P0-T22 — seed framework. Idempotent, tenant-scoped, deny-by-default.

Phase 0 ships the loader + the canonical local-dev seed *specs*. The specs are applied against the
real schema in Phase 1 (P1-T16, once the tables exist); the loader itself is DB-agnostic (any
DB-API 2.0 connection) and is verified here against stdlib sqlite3.

Invariants enforced by the loader:
- **tenant-scoped**: every seeded row MUST carry a non-empty ``tenant_id`` (raises otherwise).
- **idempotent**: a row already present (matched on its conflict keys) is skipped, so re-running
  the seed never duplicates.
- **deny-by-default**: only explicitly-listed ACLGrant rows are seeded; no implicit grants.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SeedSpec:
    """A set of rows for one table, with the columns that identify a duplicate."""

    table: str
    conflict_keys: tuple[str, ...]
    rows: tuple[dict, ...] = ()


class SeedLoader:
    def __init__(self, conn) -> None:
        self._conn = conn

    def _exists(self, spec: SeedSpec, row: dict) -> bool:
        where = " AND ".join(f"{k} = ?" for k in spec.conflict_keys)
        params = [row[k] for k in spec.conflict_keys]
        cur = self._conn.execute(f"SELECT 1 FROM {spec.table} WHERE {where} LIMIT 1", params)
        return cur.fetchone() is not None

    def apply(self, specs: list[SeedSpec]) -> dict[str, int]:
        """Insert missing rows. Returns {table: inserted_count}. Idempotent."""
        inserted: dict[str, int] = {}
        for spec in specs:
            count = 0
            for row in spec.rows:
                if not row.get("tenant_id"):
                    raise ValueError(
                        f"seed row for {spec.table!r} missing tenant_id (tenant-scoped invariant)"
                    )
                if self._exists(spec, row):
                    continue
                cols = ", ".join(row.keys())
                ph = ", ".join("?" for _ in row)
                self._conn.execute(
                    f"INSERT INTO {spec.table} ({cols}) VALUES ({ph})", list(row.values())
                )
                count += 1
            inserted[spec.table] = count
        self._conn.commit()
        return inserted


def default_local_seed_specs() -> list[SeedSpec]:
    """Canonical local-dev seed: one tenant, one collection, one API key, explicit ACL grants, and
    a no-train default provider policy. Applied in Phase 1 (P1-T16) when the tables exist.
    """
    tenant = "tenant_local"
    return [
        SeedSpec("tenant", ("tenant_id",), ({"tenant_id": tenant, "name": "Local Dev"},)),
        SeedSpec(
            "collection",
            ("tenant_id", "collection_id"),
            ({"tenant_id": tenant, "collection_id": "default", "name": "Default"},),
        ),
        SeedSpec(
            "api_client",
            ("tenant_id", "api_client_id"),
            ({"tenant_id": tenant, "api_client_id": "local-dev-key", "status": "active"},),
        ),
        # deny-by-default: only this explicit grant is seeded.
        SeedSpec(
            "acl_grant",
            ("tenant_id", "scope_type", "scope_id", "subject_type", "subject_id"),
            (
                {
                    "tenant_id": tenant,
                    "scope_type": "collection",
                    "scope_id": "default",
                    "subject_type": "role",
                    "subject_id": "reader",
                    "permission": "read",
                },
            ),
        ),
        SeedSpec(
            "provider_policy",
            ("tenant_id", "provider_policy_id"),
            (
                {
                    "tenant_id": tenant,
                    "provider_policy_id": "default-no-train",
                    "no_train_required": 1,
                    "zero_retention_required": 1,
                    "status": "active",
                },
            ),
        ),
    ]


__all__ = ["SeedLoader", "SeedSpec", "default_local_seed_specs"]
