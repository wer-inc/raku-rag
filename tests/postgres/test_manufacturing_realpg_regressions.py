"""Tier B (real Postgres) — regression gates for two manufacturing-overlay bugs that only the
DEPLOYED ProductionSystem path exhibits, surfaced by a live answer-service end-to-end smoke and
INVISIBLE to the in-memory Tier-A backend (so the green gate missed them). Mechanism-pinning per
loop-engineering §3: a clean system must pass these, and each pins the exact failing mechanism.

1. Audit writer / non-block safety_block_reason: the manufacturing_audit_events check constraint
   allows only NULL or a SafetyBlockReason value. The Postgres writer used to write "" for a
   non-block event (``_enum_value(None)`` -> ``str(None or "")``), violating the constraint and
   500-ing every audited non-block operation (it took down the Operations dashboard/telemetry/kpi).
   The fix writes NULL; a real block reason is still written unchanged (positive control below).

2. PostgresVectorStore.iter_items: the manufacturing metadata propagation + ACL-denial survey use
   the in-memory store's ``iter_items()`` bulk seam. PostgresVectorStore never implemented it, so
   document-approval transition (-> propagate_to_chunks -> iter_items) 500-ed over real PG with an
   AttributeError. The fix implements it as an RLS-scoped chunk scan.

Discoverable by the normal suite but SKIPPED unless a Postgres is reachable (mirrors the other
``tests/postgres`` suites), so Tier A stays Docker-free. Runs for real in CI ``gate.yml`` tier-b.
"""

from __future__ import annotations

import os
import unittest

from raku_rag.domain.models import IdentityClaims
from raku_rag.manufacturing.domain.audit import AuditLogEntry
from raku_rag.manufacturing.domain.safety import SafetyBlockReason

# NOTE: psycopg-dependent imports (PostgresManufacturingAuditLogWriter, ProductionSystem) are made
# inside setUp/tests — never at module top — so Tier-A `unittest discover` can collect this file even
# when psycopg is not installed (the suite then skips via @skipUnless). Mirrors the other tests/postgres.

DSN = os.environ.get("POSTGRES_URL", "postgresql://raku:raku@127.0.0.1:5432/raku_parity")
T = "mfg_realpg_reg"


def _postgres_available() -> bool:
    try:
        import psycopg

        with psycopg.connect(DSN, connect_timeout=2) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM information_schema.tables "
                    "WHERE table_name = 'manufacturing_audit_events'"
                )
                return cur.fetchone() is not None
    except Exception:
        return False


def _entry(log_id: str, *, block: SafetyBlockReason | None) -> AuditLogEntry:
    return AuditLogEntry(
        tenant_id=T,
        log_id=log_id,
        timestamp="2026-06-22T00:00:00+00:00",
        actor_id="op",
        action="answer.decided",
        resource_type="answer",
        resource_id="q1",
        decision="ok" if block is None else "blocked",
        safety_block_reason=block,
    )


@unittest.skipUnless(_postgres_available(), "Postgres not reachable (Tier B / local-only)")
class TestManufacturingRealPgRegressions(unittest.TestCase):
    def setUp(self) -> None:
        from raku_rag.persistence.manufacturing_audit import PostgresManufacturingAuditLogWriter
        from raku_rag.production import ProductionSystem

        self._WriterCls = PostgresManufacturingAuditLogWriter
        self.sys = ProductionSystem(DSN, reset=True)
        self.addCleanup(self.sys.close)
        self.principal = IdentityClaims(tenant_id=T, user_id="op", groups=(), roles=())
        # reset=True truncates only CORE tables; clear this test tenant's audit rows (RLS-scoped,
        # autocommit) so fixed audit_event_ids do not collide across re-runs.
        with self.sys._conn.cursor() as cur:
            cur.execute("SELECT set_config('app.current_tenant_id', %s, false)", (T,))
            cur.execute("DELETE FROM manufacturing_audit_events")

    # --- bug 1: non-block audit write must persist (NULL safety_block_reason, not "") ------------
    def test_non_block_audit_event_persists_over_postgres(self) -> None:
        writer = self._WriterCls(self.sys._conn)
        # Before the fix this raised: new row violates check constraint
        # manufacturing_audit_events_safety_block_reason_check (value was "").
        writer.record(_entry("audit:nonblock:1", block=None))

        with self.sys._conn.cursor() as cur:
            cur.execute(
                "SELECT safety_block_reason FROM manufacturing_audit_events "
                "WHERE audit_event_id = %s",
                ("audit:nonblock:1",),
            )
            row = cur.fetchone()
        self.assertIsNotNone(row, "the non-block audit row must persist")
        self.assertIsNone(row[0], "no-block safety_block_reason must be SQL NULL, never ''")

        entries = writer.read_all(self.principal)
        got = next((e for e in entries if e.log_id == "audit:nonblock:1"), None)
        self.assertIsNotNone(got, "the non-block entry must read back")
        self.assertIsNone(got.safety_block_reason)

    def test_block_audit_event_still_writes_reason_over_postgres(self) -> None:
        # Positive control: the fix must NOT swallow a real block reason.
        writer = self._WriterCls(self.sys._conn)
        writer.record(_entry("audit:block:1", block=SafetyBlockReason.APPROVED_CITATION_MISSING))
        with self.sys._conn.cursor() as cur:
            cur.execute(
                "SELECT safety_block_reason FROM manufacturing_audit_events "
                "WHERE audit_event_id = %s",
                ("audit:block:1",),
            )
            row = cur.fetchone()
        self.assertEqual(row[0], "approved_citation_missing")

    # --- bug 2: PostgresVectorStore.iter_items must scan the tenant's chunks --------------------
    def test_postgres_vector_store_iter_items_scans_chunks(self) -> None:
        self.sys.ingest_text(
            tenant_id=T,
            collection_id="c",
            document_id="d1",
            text="The maintenance interval for pump P-12 is ninety days per the equipment manual.",
        )
        # Before the fix: AttributeError: 'PostgresVectorStore' object has no attribute 'iter_items'.
        items = self.sys.store.iter_items()
        self.assertIsInstance(items, tuple)
        self.assertTrue(items, "iter_items must return the ingested chunk(s)")
        docs = {chunk.document_id for chunk, _vec in items}
        self.assertIn("d1", docs)
        chunk, _vec = items[0]
        self.assertEqual(chunk.tenant_id, T, "iter_items is RLS-scoped to the current tenant")


if __name__ == "__main__":
    unittest.main()
