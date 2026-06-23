"""Postgres manufacturing audit writer contracts."""

from __future__ import annotations

import json
import unittest

from raku_rag.core.errors import TenantIsolationError
from raku_rag.domain.models import IdentityClaims
from raku_rag.manufacturing.domain.audit import AuditLogEntry
from raku_rag.manufacturing.domain.safety import SafetyBlockReason
from raku_rag.persistence.manufacturing_audit import PostgresManufacturingAuditLogWriter


class _FakeCursor:
    def __init__(self, conn: "_FakeConnection") -> None:
        self.conn = conn
        self._rows: list[tuple] = []
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
        self.audit_rows: list[tuple] = []
        self.executed: list[tuple[str, tuple]] = []

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self)


def _claims(tenant_id: str = "tenant_mfg") -> IdentityClaims:
    return IdentityClaims(tenant_id=tenant_id, user_id="admin")


def _entry(log_id: str, tenant_id: str = "tenant_mfg", **overrides) -> AuditLogEntry:
    base = dict(
        tenant_id=tenant_id,
        log_id=log_id,
        timestamp="2026-06-22T00:00:00Z",
        actor_id="alice",
        action="answer.generated",
        resource_type="answer",
        resource_id="ans_1",
        decision="ok",
        reason="approved by bob@example.com",
        factory_id="factory_1",
        department_id="dept_1",
        high_risk_classification_result=True,
        safety_block_reason=SafetyBlockReason.APPROVED_CITATION_MISSING,
        citation_ids=("cit_1",),
        document_ids_used=("doc_1",),
    )
    base.update(overrides)
    return AuditLogEntry(**base)


class TestPostgresManufacturingAuditWriter(unittest.TestCase):
    def test_record_readback_redacts_and_preserves_hash_chain(self) -> None:
        writer = PostgresManufacturingAuditLogWriter(_FakeConnection())

        writer.record(_entry("log_1"))
        writer.record(_entry("log_2", resource_id="ans_2"))
        rows = writer.read_all(_claims())

        self.assertEqual([row.log_id for row in rows], ["log_1", "log_2"])
        self.assertNotIn("bob@example.com", rows[0].reason or "")
        self.assertEqual(rows[0].document_ids_used, ("doc_1",))
        self.assertEqual(rows[1].prev_hash, rows[0].entry_hash)
        self.assertTrue(writer.verify_chain(_claims()))

    def test_tenant_scoped_readback(self) -> None:
        writer = PostgresManufacturingAuditLogWriter(_FakeConnection())
        writer.record(_entry("a1", tenant_id="A"))
        writer.record(_entry("b1", tenant_id="B"))

        self.assertEqual([entry.log_id for entry in writer.read_all(_claims("A"))], ["a1"])
        with self.assertRaises(TenantIsolationError):
            writer.read_for_tenant(_claims("A"), "B")

    def test_tampered_payload_breaks_chain(self) -> None:
        conn = _FakeConnection()
        writer = PostgresManufacturingAuditLogWriter(conn)
        writer.record(_entry("log_1"))
        payload = json.loads(conn.audit_rows[0][15])
        payload["resource_id"] = "tampered"
        row = list(conn.audit_rows[0])
        row[15] = json.dumps(payload)
        conn.audit_rows[0] = tuple(row)

        self.assertFalse(writer.verify_chain(_claims()))


if __name__ == "__main__":
    unittest.main()
