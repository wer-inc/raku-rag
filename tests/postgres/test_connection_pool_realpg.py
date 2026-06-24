"""Tier B (real Postgres) — P3-2: the connection pool is maintained under concurrent load AND keeps
RLS tenant isolation per request.

Proves the production-relevant property: with the pool, N concurrent multi-tenant requests each run on
their OWN connection with their OWN tenant GUC, so RLS blocks cross-tenant reads under concurrency, the
pool stays bounded, and every connection is returned (no leak). This is why pooling — not a single shared
connection — is required to scale the answer path safely. Skip-safe without Postgres (Tier A stays
Docker-free).
"""

from __future__ import annotations

import os
import unittest
from concurrent.futures import ThreadPoolExecutor

DSN = os.environ.get("POSTGRES_URL", "postgresql://raku:raku@127.0.0.1:5432/raku_parity")
TENANTS = [f"pool_t_{i}" for i in range(5)]


def _postgres_available() -> bool:
    try:
        import psycopg

        with psycopg.connect(DSN, connect_timeout=2) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM information_schema.tables WHERE table_name = 'documents'"
                )
                return cur.fetchone() is not None
    except Exception:
        return False


@unittest.skipUnless(_postgres_available(), "Postgres not reachable (Tier B / local-only)")
class TestConnectionPoolRealPG(unittest.TestCase):
    def setUp(self) -> None:
        import psycopg

        # seed one document per tenant as the owning login role (RLS bypassed for setup)
        with psycopg.connect(DSN, autocommit=True) as conn, conn.cursor() as cur:
            for t in TENANTS:
                cur.execute(
                    "INSERT INTO tenants(tenant_id,name) VALUES (%s,%s) ON CONFLICT DO NOTHING",
                    (t, t),
                )
                cur.execute(
                    "INSERT INTO collections(collection_id,tenant_id,name) "
                    "VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                    (f"{t}_c", t, t),
                )
                cur.execute(
                    "INSERT INTO documents(document_id,tenant_id,collection_id,source_id,"
                    "source_document_id,indexed_at) VALUES (%s,%s,%s,'s','sd',now()) "
                    "ON CONFLICT DO NOTHING",
                    (f"{t}_doc", t, f"{t}_c"),
                )

    def test_pool_isolation_and_bounded_under_concurrency(self) -> None:
        from raku_rag.persistence.pool import PostgresConnectionPool

        pool = PostgresConnectionPool(DSN, size=4)
        self.addCleanup(pool.close)
        leaks: list[str] = []

        def worker(i: int) -> None:
            tenant = TENANTS[i % len(TENANTS)]
            with pool.acquire() as conn:
                cur = conn.cursor()
                try:
                    # each request: its OWN connection, role, and tenant GUC (RLS enforced)
                    cur.execute("SET ROLE raku_app")
                    cur.execute("SELECT set_config('app.current_tenant_id', %s, false)", (tenant,))
                    # sees its own doc
                    cur.execute(
                        "SELECT count(*) FROM documents WHERE document_id = %s", (f"{tenant}_doc",)
                    )
                    if cur.fetchone()[0] != 1:
                        leaks.append(f"{tenant}: cannot see own doc")
                    # cannot see another tenant's doc (cross-tenant probe under concurrency)
                    other = TENANTS[(i + 1) % len(TENANTS)]
                    cur.execute(
                        "SELECT count(*) FROM documents WHERE document_id = %s", (f"{other}_doc",)
                    )
                    if cur.fetchone()[0] != 0:
                        leaks.append(f"{tenant}: LEAKED {other}'s doc")
                finally:
                    cur.execute("RESET ROLE")  # clean the pooled connection for the next acquirer
                    cur.close()

        errors = 0
        with ThreadPoolExecutor(max_workers=8) as ex:
            futures = [ex.submit(worker, i) for i in range(160)]
            for f in futures:
                try:
                    f.result()
                except Exception:
                    errors += 1

        self.assertEqual(errors, 0, "no errors under concurrent pooled load")
        self.assertEqual(leaks, [], f"RLS isolation must hold under concurrency; leaks={leaks}")
        # the pool is bounded and every connection was returned (no leak)
        self.assertEqual(pool.size(), 4)
        self.assertEqual(pool.available(), 4, "all pooled connections returned after load")


if __name__ == "__main__":
    unittest.main()
