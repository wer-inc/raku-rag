"""★G3b/★G5 Tier B — 実測運用メトリクス over real Postgres (query_traces.query_redacted, 0025).

Skipped unless a Postgres with the 0025 migration applied is reachable (same conditional-skip
posture as test_query_trace_realpg). Verifies the answer path persists the PII-REDACTED question
text, that PostgresQueryTraceReader.operational_summary aggregates real latency/status data, and
that the summary is RLS-isolated per tenant (tenant B sees zero of tenant A).
"""

from __future__ import annotations

import os
import unittest

DSN = os.environ.get("POSTGRES_URL", "postgresql://raku:raku@127.0.0.1:5432/raku_parity")


def _query_redacted_available() -> bool:
    try:
        import psycopg

        with psycopg.connect(DSN, connect_timeout=2) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_name = 'query_traces' AND column_name = 'query_redacted'"
                )
                return cur.fetchone() is not None
    except Exception:
        return False


@unittest.skipUnless(
    _query_redacted_available(),
    "Postgres with 0025_query_trace_query_redacted not reachable (Tier B / local-only)",
)
class TestQualityOperationalRealPg(unittest.TestCase):
    def setUp(self) -> None:
        from raku_rag.persistence.telemetry import PostgresQueryTraceReader
        from raku_rag.production import ProductionSystem

        self.sys = ProductionSystem(DSN, reset=True)
        self.addCleanup(self.sys.close)
        self.reader = PostgresQueryTraceReader(self.sys._conn)

    def _seed(self, tenant: str, user: str) -> None:
        from raku_rag.domain.models import ScopeType, SubjectType

        self.sys.ingest_text(
            tenant_id=tenant,
            collection_id="manuals",
            document_id=f"doc_{tenant}",
            text="The maintenance interval for pump P-12 is ninety days per the manual.",
        )
        self.sys.grant(tenant, ScopeType.COLLECTION, "manuals", SubjectType.USER, user)

    def _answer(self, tenant: str, user: str, query: str):
        from tests.helpers import claims

        return self.sys.answer(claims(tenant, user), query)

    def _rows(self, tenant: str, sql: str, params: tuple) -> list:
        from raku_rag.persistence.postgres import _use_tenant

        _use_tenant(self.sys._conn, tenant)
        with self.sys._conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()

    def test_summary_aggregates_real_traces_and_redacts_query_text(self) -> None:
        self._seed("tenant_a", "alice")
        ok = self._answer("tenant_a", "alice", "maintenance interval for pump P-12?")
        self.assertEqual(ok.status, "ok")
        refused = self._answer(
            "tenant_a",
            "alice",
            "what is the daily quota for widget Z-99? mail alice@example.com",
        )
        self.assertNotEqual(refused.status, "ok")

        # The persisted row carries the question ONLY after PII redaction.
        rows = self._rows(
            "tenant_a",
            "SELECT query_redacted FROM query_traces WHERE request_id = %s",
            (refused.correlation_id,),
        )
        self.assertEqual(len(rows), 1)
        self.assertNotIn("alice@example.com", rows[0][0])
        self.assertIn("[REDACTED:email]", rows[0][0])

        summary = self.reader.operational_summary("tenant_a")
        self.assertEqual(summary["query_count"], 2)
        self.assertGreater(summary["p50_ms"], 0.0)
        self.assertGreaterEqual(summary["p95_ms"], summary["p50_ms"])
        self.assertEqual(summary["status_counts"].get("ok"), 1)
        self.assertEqual(sum(summary["status_counts"].values()), 2)
        refusals = summary["recent_refusals"]
        self.assertEqual([r["request_id"] for r in refusals], [refused.correlation_id])
        self.assertIn("[REDACTED:email]", refusals[0]["query_redacted"])
        self.assertNotIn("alice@example.com", refusals[0]["query_redacted"])
        self.assertTrue(refusals[0]["created_at"])  # real timestamp from Postgres

    def test_summary_is_rls_isolated_per_tenant(self) -> None:
        self._seed("tenant_a", "alice")
        self._answer("tenant_a", "alice", "maintenance interval for pump P-12?")
        self._answer("tenant_a", "alice", "unanswerable question about widget Z-99")

        summary_b = self.reader.operational_summary("tenant_b")
        self.assertEqual(summary_b["query_count"], 0)
        self.assertEqual(summary_b["status_counts"], {})
        self.assertEqual(summary_b["recent_refusals"], [])
        self.assertEqual(summary_b["insufficient_rate"], 0.0)

        # And tenant_a's own view still sees its data after the tenant_b read (RLS context swap).
        summary_a = self.reader.operational_summary("tenant_a")
        self.assertEqual(summary_a["query_count"], 2)


if __name__ == "__main__":
    unittest.main()
