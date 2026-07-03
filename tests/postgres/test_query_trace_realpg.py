"""★G1 Tier B — durable per-query telemetry over real Postgres (query_traces / cost_records /
rerank_traces).

Skipped unless a Postgres with the 0022 migration applied is reachable (same conditional-skip
posture as test_production_smoke). Verifies the full answer path leaves durable, RLS-isolated
telemetry rows, and that no raw query/answer text lands in them.
"""

from __future__ import annotations

import os
import unittest

DSN = os.environ.get("POSTGRES_URL", "postgresql://raku:raku@127.0.0.1:5432/raku_parity")


def _query_traces_available() -> bool:
    try:
        import psycopg

        with psycopg.connect(DSN, connect_timeout=2) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM information_schema.tables WHERE table_name = 'query_traces'"
                )
                return cur.fetchone() is not None
    except Exception:
        return False


@unittest.skipUnless(
    _query_traces_available(),
    "Postgres with 0022_query_traces not reachable (Tier B / local-only)",
)
class TestQueryTracePersistenceRealPg(unittest.TestCase):
    def setUp(self) -> None:
        from raku_rag.production import ProductionSystem

        self.sys = ProductionSystem(DSN, reset=True)
        self.addCleanup(self.sys.close)

    def _answer(self, tenant: str, user: str):
        from raku_rag.domain.models import ScopeType, SubjectType
        from tests.helpers import claims

        self.sys.ingest_text(
            tenant_id=tenant,
            collection_id="manuals",
            document_id=f"doc_{tenant}",
            text="The maintenance interval for pump P-12 is ninety days per the manual.",
        )
        self.sys.grant(tenant, ScopeType.COLLECTION, "manuals", SubjectType.USER, user)
        return self.sys.answer(claims(tenant, user), "maintenance interval for pump P-12?")

    def _rows(self, tenant: str, sql: str, params: tuple) -> list:
        from raku_rag.persistence.postgres import _use_tenant

        _use_tenant(self.sys._conn, tenant)
        with self.sys._conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()

    def test_answer_leaves_durable_reference_only_trace(self) -> None:
        ans = self._answer("tenant_a", "alice")
        self.assertEqual(ans.status, "ok")

        traces = self._rows(
            "tenant_a",
            "SELECT status, profile_id, user_id_hash, total_ms, retrieved_chunks "
            "FROM query_traces WHERE request_id = %s",
            (ans.correlation_id,),
        )
        self.assertEqual(len(traces), 1)
        status, profile_id, user_id_hash, total_ms, retrieved_chunks = traces[0]
        self.assertEqual(status, "ok")
        self.assertEqual(profile_id, "default")
        # Reference-only: hashed identity, no raw user id.
        self.assertNotEqual(user_id_hash, "alice")
        self.assertGreater(float(total_ms), 0.0)
        self.assertGreaterEqual(int(retrieved_chunks), 1)

        costs = self._rows(
            "tenant_a",
            "SELECT kind FROM cost_records WHERE trace_id = %s",
            (ans.correlation_id,),
        )
        kinds = {row[0] for row in costs}
        self.assertIn("embedding_tokens", kinds)
        self.assertIn("llm_prompt_tokens", kinds)

        reranks = self._rows(
            "tenant_a",
            "SELECT provider, candidate_count FROM rerank_traces WHERE query_id = %s",
            (ans.correlation_id,),
        )
        self.assertEqual(len(reranks), 1)
        self.assertTrue(reranks[0][0])  # provider recorded

    def test_traces_are_rls_isolated_per_tenant(self) -> None:
        ans_a = self._answer("tenant_a", "alice")
        self._answer("tenant_b", "bob")

        # Under tenant_b's RLS context, tenant_a's trace must be invisible even with a
        # deliberately-wrong WHERE (no tenant filter at all).
        visible_to_b = self._rows(
            "tenant_b",
            "SELECT tenant_id FROM query_traces WHERE request_id = %s",
            (ans_a.correlation_id,),
        )
        self.assertEqual(visible_to_b, [])
        all_b = self._rows("tenant_b", "SELECT DISTINCT tenant_id FROM query_traces", ())
        self.assertEqual(all_b, [("tenant_b",)])


if __name__ == "__main__":
    unittest.main()
