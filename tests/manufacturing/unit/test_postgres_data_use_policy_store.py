"""Postgres DataUsePolicy store contracts."""

from __future__ import annotations

import unittest

from raku_rag.domain.models import IdentityClaims
from raku_rag.manufacturing.domain.policy import NoTrainFallback
from raku_rag.persistence.manufacturing_governance import PostgresDataUsePolicyStore


class _FakeCursor:
    def __init__(self, conn: "_FakeConnection") -> None:
        self.conn = conn
        self._row: tuple | None = None

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def execute(self, sql: str, params: tuple | None = None) -> None:
        params = params or ()
        self.conn.executed.append((sql, params))
        if "set_config('app.current_tenant_id'" in sql:
            self.conn.current_tenant = params[0]
            return
        if sql.startswith("SELECT tenant_id"):
            tenant_id = params[0]
            self._row = self.conn.rows.get(tenant_id)
            return
        if sql.startswith("INSERT INTO manufacturing_data_use_policies"):
            self.conn.rows.setdefault(params[0], params)
            return
        if sql.startswith("UPDATE manufacturing_data_use_policies"):
            tenant_id = params[-1]
            current = self.conn.rows[tenant_id]
            self.conn.rows[tenant_id] = (
                tenant_id,
                params[0],
                params[1],
                params[2],
                params[3],
                params[4],
                params[5],
                params[6],
                params[7],
                params[8],
                params[9],
                params[10],
            )
            self.assert_same_tenant(current[0], tenant_id)

    def fetchone(self):
        return self._row

    def assert_same_tenant(self, left: str, right: str) -> None:
        if left != right:
            raise AssertionError(f"tenant mismatch: {left} != {right}")


class _FakeConnection:
    def __init__(self) -> None:
        self.current_tenant = ""
        self.rows: dict[str, tuple] = {}
        self.executed: list[tuple[str, tuple]] = []

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self)


def _admin(tenant_id: str = "tenant_mfg") -> IdentityClaims:
    return IdentityClaims(tenant_id=tenant_id, user_id="admin", roles=("admin",))


class TestPostgresDataUsePolicyStore(unittest.TestCase):
    def test_get_auto_seeds_safe_default(self) -> None:
        store = PostgresDataUsePolicyStore(_FakeConnection())

        policy = store.get("tenant_mfg")

        self.assertTrue(policy.no_train_default)
        self.assertFalse(policy.training_opt_in)
        self.assertIsNone(policy.opt_in_contract_ref)
        self.assertTrue(policy.provider_no_train_required)
        self.assertEqual(policy.no_train_fallback, NoTrainFallback.BLOCK)
        self.assertEqual(policy.retention_customer, 365)
        self.assertEqual(policy.retention_audit, 365)
        self.assertEqual(policy.policy_version, "1")

    def test_update_bumps_version_and_is_tenant_scoped(self) -> None:
        conn = _FakeConnection()
        store = PostgresDataUsePolicyStore(conn)
        store.get("tenant_mfg")

        updated = store.update(
            "tenant_mfg",
            {"export_enabled": True, "retention_customer": 730},
            _admin(),
        )

        self.assertTrue(updated.export_enabled)
        self.assertEqual(updated.retention_customer, 730)
        self.assertEqual(updated.policy_version, "2")
        self.assertEqual(updated.updated_by, "admin")
        self.assertEqual(conn.current_tenant, "tenant_mfg")

    def test_opt_in_requires_contract_ref_and_does_not_persist_invalid_patch(self) -> None:
        store = PostgresDataUsePolicyStore(_FakeConnection())
        before = store.get("tenant_mfg")

        with self.assertRaises(ValueError):
            store.update("tenant_mfg", {"training_opt_in": True}, _admin())

        after = store.get("tenant_mfg")
        self.assertEqual(after.policy_version, before.policy_version)
        self.assertFalse(after.training_opt_in)

    def test_opt_in_with_contract_ref_succeeds(self) -> None:
        store = PostgresDataUsePolicyStore(_FakeConnection())

        policy = store.update(
            "tenant_mfg",
            {"training_opt_in": True, "opt_in_contract_ref": "CONTRACT-1"},
            _admin(),
        )

        self.assertTrue(policy.training_opt_in)
        self.assertEqual(policy.opt_in_contract_ref, "CONTRACT-1")


if __name__ == "__main__":
    unittest.main()
