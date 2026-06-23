"""Postgres-backed manufacturing governance stores."""

from __future__ import annotations

import copy

from raku_rag.domain.models import IdentityClaims
from raku_rag.manufacturing.domain.policy import DataUsePolicy, NoTrainFallback
from raku_rag.manufacturing.governance.no_train import default_policy
from raku_rag.persistence.postgres import _use_tenant

_PATCHABLE_FIELDS = frozenset(
    {
        "no_train_default",
        "training_opt_in",
        "opt_in_contract_ref",
        "provider_no_train_required",
        "no_train_fallback",
        "retention_customer",
        "retention_audit",
        "export_enabled",
        "updated_by",
        "updated_at",
    }
)


class PostgresDataUsePolicyStore:
    """Durable DataUsePolicy store with the same safety posture as the in-memory store."""

    def __init__(self, conn) -> None:
        self._conn = conn

    def get(self, tenant_id: str) -> DataUsePolicy:
        _use_tenant(self._conn, tenant_id)
        policy = self._fetch(tenant_id)
        if policy is not None:
            return copy.copy(policy)
        policy = default_policy(tenant_id)
        self._insert(policy)
        return copy.copy(policy)

    def update(self, tenant_id: str, patch: dict, actor: IdentityClaims) -> DataUsePolicy:
        unknown = set(patch) - _PATCHABLE_FIELDS
        if unknown:
            raise ValueError(f"non-patchable field(s): {sorted(unknown)}")

        current = self.get(tenant_id)
        candidate = copy.copy(current)
        for key, value in patch.items():
            if key == "no_train_fallback" and isinstance(value, str):
                value = NoTrainFallback(value)
            setattr(candidate, key, value)
        candidate.tenant_id = tenant_id
        candidate.policy_version = _next_version(current.policy_version)
        if actor is not None and patch.get("updated_by") is None:
            candidate.updated_by = actor.user_id
        _validate(candidate)
        self._update(candidate)
        return copy.copy(candidate)

    def _fetch(self, tenant_id: str) -> DataUsePolicy | None:
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT tenant_id, no_train_default, training_opt_in, opt_in_contract_ref, "
                "provider_no_train_required, no_train_fallback, retention_customer, "
                "retention_audit, export_enabled, policy_version, updated_by, updated_at "
                "FROM manufacturing_data_use_policies WHERE tenant_id = %s",
                (tenant_id,),
            )
            row = cur.fetchone()
        return _row_to_policy(row) if row else None

    def _insert(self, policy: DataUsePolicy) -> None:
        _use_tenant(self._conn, policy.tenant_id)
        with self._conn.cursor() as cur:
            cur.execute(
                "INSERT INTO manufacturing_data_use_policies (tenant_id, no_train_default, "
                "training_opt_in, opt_in_contract_ref, provider_no_train_required, "
                "no_train_fallback, retention_customer, retention_audit, export_enabled, "
                "policy_version, updated_by, updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (tenant_id) DO NOTHING",
                _policy_params(policy),
            )

    def _update(self, policy: DataUsePolicy) -> None:
        _use_tenant(self._conn, policy.tenant_id)
        with self._conn.cursor() as cur:
            cur.execute(
                "UPDATE manufacturing_data_use_policies SET no_train_default=%s, "
                "training_opt_in=%s, opt_in_contract_ref=%s, provider_no_train_required=%s, "
                "no_train_fallback=%s, retention_customer=%s, retention_audit=%s, "
                "export_enabled=%s, policy_version=%s, updated_by=%s, updated_at=%s "
                "WHERE tenant_id=%s",
                (
                    policy.no_train_default,
                    policy.training_opt_in,
                    policy.opt_in_contract_ref,
                    policy.provider_no_train_required,
                    policy.no_train_fallback.value,
                    policy.retention_customer,
                    policy.retention_audit,
                    policy.export_enabled,
                    policy.policy_version,
                    policy.updated_by,
                    policy.updated_at,
                    policy.tenant_id,
                ),
            )


def _policy_params(policy: DataUsePolicy) -> tuple:
    return (
        policy.tenant_id,
        policy.no_train_default,
        policy.training_opt_in,
        policy.opt_in_contract_ref,
        policy.provider_no_train_required,
        policy.no_train_fallback.value,
        policy.retention_customer,
        policy.retention_audit,
        policy.export_enabled,
        policy.policy_version,
        policy.updated_by,
        policy.updated_at,
    )


def _row_to_policy(row) -> DataUsePolicy:
    return DataUsePolicy(
        tenant_id=row[0],
        no_train_default=bool(row[1]),
        training_opt_in=bool(row[2]),
        opt_in_contract_ref=row[3],
        provider_no_train_required=bool(row[4]),
        no_train_fallback=NoTrainFallback(row[5]),
        retention_customer=int(row[6]),
        retention_audit=int(row[7]),
        export_enabled=bool(row[8]),
        policy_version=row[9],
        updated_by=row[10],
        updated_at=row[11],
    )


def _validate(policy: DataUsePolicy) -> None:
    if policy.training_opt_in and not (policy.opt_in_contract_ref or "").strip():
        raise ValueError(
            "training_opt_in=True requires a non-empty opt_in_contract_ref (FR-MFG-018)"
        )


def _next_version(current: str) -> str:
    try:
        return str(int(current) + 1)
    except (TypeError, ValueError):
        return "2"
