"""Audit sink durability and redaction contracts."""

from __future__ import annotations

import unittest

from raku_rag.observability.audit import AuditEvent, InMemoryAuditSink
from raku_rag.persistence.postgres import PostgresAuditSink


class _FakeCursor:
    def __init__(self, conn: "_FakeConnection") -> None:
        self.conn = conn
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
        if sql.startswith("INSERT INTO tenants"):
            self.conn.tenants.add(params[0])
            return
        if sql.startswith("INSERT INTO audit_logs"):
            self.conn.audit_rows.append(params)
            return
        if sql.startswith("SELECT log_id"):
            correlation = params[0] if params else ""
            self._rows = [
                row
                for row in self.conn.audit_rows
                if row[1] == self.conn.current_tenant and (not correlation or row[5] == correlation)
            ]

    def fetchall(self) -> list[tuple]:
        return list(self._rows)


class _FakeConnection:
    def __init__(self) -> None:
        self.current_tenant = ""
        self.tenants: set[str] = set()
        self.audit_rows: list[tuple] = []
        self.executed: list[tuple[str, tuple]] = []

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self)


class AuditSinkTest(unittest.TestCase):
    def test_in_memory_sink_redacts_nested_metadata(self) -> None:
        sink = InMemoryAuditSink()

        event = sink.record(
            AuditEvent(
                tenant_id="tenant_a",
                correlation_id="trace_a",
                action="answer",
                decision="ok for alice@example.com",
                reason="review bob@example.com",
                metadata={"nested": {"owner": "carol@example.com"}},
            )
        )

        serialized = repr(event)
        self.assertNotIn("alice@example.com", serialized)
        self.assertNotIn("bob@example.com", serialized)
        self.assertNotIn("carol@example.com", serialized)

    def test_postgres_sink_persists_reference_only_redacted_audit_events(self) -> None:
        conn = _FakeConnection()
        sink = PostgresAuditSink(conn)

        saved = sink.record(
            AuditEvent(
                tenant_id="tenant_a",
                correlation_id="trace_a",
                action="answer",
                decision="ok",
                actor_id="alice@example.com",
                resource_type="query",
                resource_id="q1",
                document_ids=("doc_1",),
                chunk_ids=("chunk_1",),
                reason="manual review by bob@example.com",
                metadata={
                    "request_id": "req_1",
                    "trace_id": "trace_a",
                    "citation_ids": ("cite_1",),
                    "pii_redaction_applied": True,
                },
            )
        )
        sink.record(
            AuditEvent(
                tenant_id="tenant_b",
                correlation_id="trace_b",
                action="answer",
                decision="ok",
                resource_type="query",
            )
        )

        self.assertEqual(saved.reason, "manual review by [REDACTED:email]")
        self.assertIn("tenant_a", conn.tenants)
        inserted = conn.audit_rows[0]
        self.assertEqual(inserted[1], "tenant_a")
        self.assertEqual(inserted[5], "trace_a")
        self.assertEqual(inserted[20], ["doc_1"])
        self.assertEqual(inserted[21], ["chunk_1"])
        self.assertNotIn("bob@example.com", repr(inserted))

        rows = sink.events("tenant_a", correlation_id="trace_a")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].tenant_id, "tenant_a")
        self.assertEqual(rows[0].correlation_id, "trace_a")
        self.assertEqual(rows[0].document_ids, ("doc_1",))
        self.assertEqual(rows[0].chunk_ids, ("chunk_1",))
        self.assertEqual(rows[0].metadata["citation_ids"], ("cite_1",))
        self.assertTrue(rows[0].metadata["pii_redaction_applied"])

    def test_postgres_sink_requires_tenant_for_reads(self) -> None:
        with self.assertRaises(ValueError):
            PostgresAuditSink(_FakeConnection()).events()


if __name__ == "__main__":
    unittest.main()
