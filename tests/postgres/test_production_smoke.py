"""Smoke test for the Postgres-backed ProductionSystem (001 production track, Step 2).

Discoverable by the normal suite but SKIPPED unless a Postgres is reachable (mirrors
``tests/integration/test_stack_boot.py``'s docker-conditional skip), so Tier A stays Docker-free. The
authoritative parity is the full ``tests/security/*`` suite run with ``RAKU_TEST_BACKEND=postgres`` in
Tier B (``scripts/gate.sh b``); this smoke just proves the adapter wires up end-to-end.
"""

from __future__ import annotations

import os
import unittest

from raku_rag.domain.models import ScopeType, SubjectType

DSN = os.environ.get("POSTGRES_URL", "postgresql://raku:raku@127.0.0.1:5432/raku_parity")


def _postgres_available() -> bool:
    try:
        import psycopg

        with psycopg.connect(DSN, connect_timeout=2) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM information_schema.tables WHERE table_name = 'chunks'")
                return cur.fetchone() is not None
    except Exception:
        return False


@unittest.skipUnless(_postgres_available(), "Postgres not reachable (Tier B / local-only)")
class TestProductionSystemSmoke(unittest.TestCase):
    def setUp(self) -> None:
        from raku_rag.production import ProductionSystem

        self.sys = ProductionSystem(DSN, reset=True)
        self.addCleanup(self.sys.close)

    def test_ingest_grant_answer_roundtrip(self) -> None:
        from tests.helpers import claims

        self.sys.ingest_text(
            tenant_id="T",
            collection_id="c",
            document_id="d1",
            text="The maintenance interval for pump P-12 is ninety days per the manual.",
        )
        self.sys.grant("T", ScopeType.COLLECTION, "c", SubjectType.USER, "alice")
        ans = self.sys.answer(
            claims("T", "alice"), "what is the maintenance interval for pump P-12?"
        )
        self.assertEqual(ans.status, "ok")
        self.assertTrue(any(c.document_id == "d1" for c in ans.citations))

    def test_tenant_isolation_and_prefilter(self) -> None:
        from tests.helpers import claims

        for t in ("A", "B"):
            self.sys.ingest_text(
                tenant_id=t,
                collection_id=f"c{t}",
                document_id=f"d{t}",
                text="The rocket fuel mixing ratio is documented in section four.",
            )
            self.sys.grant(t, ScopeType.COLLECTION, f"c{t}", SubjectType.USER, "u")
        results = self.sys.search(claims("A", "u"), "rocket fuel mixing ratio")
        self.assertTrue(results)
        self.assertTrue(all(r.chunk.tenant_id == "A" for r in results))
        # RLS + tombstone + visible pre-filter admits exactly tenant A's single chunk (parity pin).
        self.assertEqual(self.sys.store.last_prefiltered_count, 1)


if __name__ == "__main__":
    unittest.main()
