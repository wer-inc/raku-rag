"""Durable manufacturing governance wiring contracts."""

from __future__ import annotations

import json
import unittest

from raku_rag.domain.models import IdentityClaims
from raku_rag.manufacturing.app import ManufacturingSystem
from raku_rag.persistence.manufacturing_audit import PostgresManufacturingAuditLogWriter
from raku_rag.persistence.manufacturing_governance import PostgresDataUsePolicyStore


class _FakeCursor:
    def __init__(self, conn: "_FakeConnection") -> None:
        self.conn = conn
        self._row: tuple | None = None
        self._rows: list[tuple] = []

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
            self._row = self.conn.policy_rows.get(params[0])
            return
        if sql.startswith("INSERT INTO manufacturing_data_use_policies"):
            self.conn.policy_rows.setdefault(params[0], params)
            return
        if sql.startswith("UPDATE manufacturing_data_use_policies"):
            tenant_id = params[-1]
            self.conn.policy_rows[tenant_id] = (
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
            return

        if sql.startswith("SELECT entry_hash"):
            rows = [row for row in self.conn.audit_rows if row[1] == self.conn.current_tenant]
            self._row = (rows[-1][13],) if rows else None
            return
        if sql.startswith("INSERT INTO manufacturing_audit_events"):
            self.conn.audit_rows.append(params)
            return
        if sql.startswith("SELECT entry_payload"):
            self._rows = [
                (json.loads(row[15]),)
                for row in self.conn.audit_rows
                if row[1] == self.conn.current_tenant
            ]

    def fetchone(self):
        return self._row

    def fetchall(self) -> list[tuple]:
        return list(self._rows)


class _FakeConnection:
    def __init__(self) -> None:
        self.current_tenant = ""
        self.policy_rows: dict[str, tuple] = {}
        self.audit_rows: list[tuple] = []
        self.executed: list[tuple[str, tuple]] = []

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self)


def _admin(tenant_id: str = "tenant_mfg") -> IdentityClaims:
    return IdentityClaims(tenant_id=tenant_id, user_id="admin", roles=("admin",))


class TestDurableManufacturingWiring(unittest.TestCase):
    def test_injected_postgres_stores_back_policy_updates_and_audit_export(self) -> None:
        conn = _FakeConnection()
        system = ManufacturingSystem(
            audit=PostgresManufacturingAuditLogWriter(conn),
            policy_store=PostgresDataUsePolicyStore(conn),
        )
        actor = _admin()

        updated = system.update_data_use_policy(
            tenant_id=actor.tenant_id,
            patch={"retention_customer": 730},
            actor=actor,
        )

        self.assertEqual(updated.policy_version, "2")
        self.assertEqual(updated.updated_by, "admin")

        # Recreate the adapters over the same connection to prove this is persisted store state,
        # not a live object reference held by ManufacturingSystem.
        reread_policy = PostgresDataUsePolicyStore(conn).get(actor.tenant_id)
        reread_audit = PostgresManufacturingAuditLogWriter(conn)
        entries = reread_audit.read_all(actor)

        self.assertEqual(reread_policy.retention_customer, 730)
        self.assertEqual(reread_policy.policy_version, "2")
        self.assertEqual([entry.action for entry in entries], ["policy.retention.change"])
        self.assertEqual(entries[0].resource_type, "data_use_policy")
        self.assertIn("retention_customer", entries[0].reason or "")
        self.assertTrue(reread_audit.verify_chain(actor))

        exported = system.export_audit(principal=actor, fmt="dict")

        self.assertEqual(exported[0]["action"], "policy.retention.change")
        self.assertEqual(conn.audit_rows[-1][3], "audit.export")


if __name__ == "__main__":
    unittest.main()
