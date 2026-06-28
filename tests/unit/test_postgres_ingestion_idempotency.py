"""P2-3 — Postgres ingestion-run creation is race-safe under duplicate idempotency keys."""

from __future__ import annotations

import unittest

from raku_rag.persistence.postgres import PostgresIngestionRunStore
from raku_rag.workers.ingestion import IngestionJobMessage


def _row(
    *,
    run_id: str,
    tenant_id: str,
    collection_id: str,
    source_id: str,
    document_id: str,
    idempotency_key: str,
    document_ref: str,
    content_type: str,
    run_type: str,
    trigger: str,
) -> tuple:
    return (
        run_id,
        tenant_id,
        collection_id,
        source_id,
        document_id,
        run_type,
        trigger,
        "queued",
        idempotency_key,
        document_ref,
        content_type,
        "",
        0,
        0,
        "",
        "",
        "",
        "",
        "",
        None,
        None,
        "2026-06-22T00:00:00Z",
        "2026-06-22T00:00:00Z",
    )


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
        self._row = None
        if "set_config('app.current_tenant_id'" in sql:
            self.conn.current_tenant = params[0]
            return
        if sql.startswith("INSERT INTO tenants") or sql.startswith("INSERT INTO collections"):
            return
        if sql.startswith("INSERT INTO ingestion_runs"):
            key = (params[1], params[5])
            if key in self.conn.by_key:
                return
            row = _row(
                run_id=params[0],
                tenant_id=params[1],
                collection_id=params[2],
                source_id=params[3],
                document_id=params[4],
                idempotency_key=params[5],
                document_ref=params[6],
                content_type=params[7],
                run_type=params[8],
                trigger=params[9],
            )
            self.conn.runs[params[0]] = row
            self.conn.by_key[key] = params[0]
            self._row = (params[0],)
            return
        if sql.startswith("INSERT INTO document_processing_states"):
            self.conn.processing_state_upserts += 1
            return
        if "FROM ingestion_runs WHERE ingestion_run_id" in sql:
            self._row = self.conn.runs.get(params[0])
            return
        if "FROM ingestion_runs WHERE idempotency_key" in sql:
            run_id = self.conn.by_key.get((self.conn.current_tenant, params[0]))
            self._row = self.conn.runs.get(run_id or "")

    def fetchone(self):
        return self._row


class _FakeConnection:
    def __init__(self) -> None:
        self.current_tenant = ""
        self.runs: dict[str, tuple] = {}
        self.by_key: dict[tuple[str, str], str] = {}
        self.processing_state_upserts = 0
        self.executed: list[tuple[str, tuple]] = []

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self)


def _message(key: str = "same-key") -> IngestionJobMessage:
    return IngestionJobMessage(
        idempotency_key=key,
        tenant_id="tenant_a",
        collection_id="manuals",
        source_id="upload",
        document_id="doc1",
        document_ref="mem://doc1",
        content_type="text/plain",
    )


class TestPostgresIngestionIdempotency(unittest.TestCase):
    def test_duplicate_idempotency_key_returns_existing_run_without_state_reprojection(
        self,
    ) -> None:
        conn = _FakeConnection()
        store = PostgresIngestionRunStore(conn)

        first, first_created = store.create_queued(_message())
        second, second_created = store.create_queued(_message())

        self.assertTrue(first_created)
        self.assertFalse(second_created)
        self.assertEqual(first.ingestion_run_id, second.ingestion_run_id)
        self.assertEqual(conn.processing_state_upserts, 1)
        sql = "\n".join(statement for statement, _params in conn.executed)
        self.assertIn("ON CONFLICT (tenant_id, idempotency_key) DO NOTHING", sql)
        self.assertIn("RETURNING ingestion_run_id", sql)
        self.assertEqual(first.async_provider, "")
        self.assertEqual(first.async_job_id, "")


if __name__ == "__main__":
    unittest.main()
