"""T117 — performance-readiness smoke: concurrent, multi-tenant load over a larger corpus.

Pins the load harness + a deterministic perf budget AND that tenant isolation holds UNDER CONCURRENCY
(each worker asserts its answer cites only its own tenant's docs; a violation raises → counted as an
error → the test fails). Real p50/p95/p99/QPS at scale come from running the harness against the
deployed service on real infra (many tenants, large corpus); this is the sandbox smoke.
"""

from __future__ import annotations

import unittest

from raku_rag.core.config import Settings
from raku_rag.domain.models import ScopeType, SubjectType
from tests.benchmarks.load_harness import run_load
from tests.helpers import claims, fresh

TENANTS = [f"tenant_{i}" for i in range(5)]
DOCS_PER_TENANT = 8


class TestLoadSmoke(unittest.TestCase):
    def setUp(self) -> None:
        self.sys = fresh()
        self.principals = {}
        for t in TENANTS:
            for d in range(DOCS_PER_TENANT):
                self.sys.ingest_text(
                    tenant_id=t,
                    collection_id="c",
                    document_id=f"{t}_doc{d}",
                    text=f"Equipment {t} unit {d}: the maintenance interval is {d + 1} weeks.",
                )
            self.sys.grant(t, ScopeType.COLLECTION, "c", SubjectType.USER, "op")
            self.principals[t] = claims(t, "op")

    def test_concurrent_multitenant_load_within_budget_and_isolated(self) -> None:
        def call(i: int) -> None:
            tenant = TENANTS[i % len(TENANTS)]
            principal = self.principals[tenant]
            ans = self.sys.answer(
                principal, f"maintenance interval for equipment {tenant} unit {i % DOCS_PER_TENANT}"
            )
            # Isolation under concurrency: never cite another tenant's document.
            for c in ans.citations:
                if not c.document_id.startswith(f"{tenant}_"):
                    raise AssertionError(f"cross-tenant leak: {tenant} saw {c.document_id}")

        stats = run_load(call, concurrency=8, iterations=160)
        self.assertEqual(stats.errors, 0, "no failures / no cross-tenant leak under load")
        self.assertEqual(stats.count, 160)
        self.assertGreater(stats.qps, 0.0)
        # Percentiles are computed and within the configured budget (in-memory path is well under it).
        self.assertGreaterEqual(stats.p50_ms, 0.0)
        self.assertLessEqual(stats.p99_ms, Settings().target_p95_latency_ms)


if __name__ == "__main__":
    unittest.main()
