"""Step 3 — pgvector ranking parity (Postgres-backed ProductionSystem).

The in-memory ``MvpSystem`` is the oracle: ingest the same documents into both backends (the embedder is
deterministic), query both, and assert the result ORDER is identical. Plus an adversarial store-level test
for the core risk the design must NOT regress into: with ACL kept in Python, ranking in pgvector must NOT
apply a SQL ``LIMIT`` before the ACL filter, or a non-visible chunk ranked above a visible one would
truncate the visible chunk out of ``top_k``.

Skip-guarded on Postgres availability (Tier B / local-only); the security hard-gate parity lives in
``tests/security`` run with ``RAKU_TEST_BACKEND=postgres``.
"""
from __future__ import annotations

import os
import unittest

from raku_rag.domain.models import ScopeType, SubjectType
from tests.helpers import claims

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
class TestRankingParity(unittest.TestCase):
    QUERY = "turbine bearing vibration noise"
    # decreasing query-token overlap -> strictly decreasing similarity (well separated; float4-safe).
    DOCS = [
        ("d1", "turbine bearing vibration noise spectrum"),
        ("d2", "turbine bearing vibration alignment"),
        ("d3", "turbine bearing lubrication"),
        ("d4", "turbine inspection schedule"),
    ]

    def _seed(self, sys) -> None:
        for doc_id, text in self.DOCS:
            sys.ingest_text(tenant_id="T", collection_id="c", document_id=doc_id, text=text)
        sys.grant("T", ScopeType.COLLECTION, "c", SubjectType.USER, "alice")

    def test_ranking_matches_in_memory_oracle(self) -> None:
        from raku_rag.app import MvpSystem
        from raku_rag.production import ProductionSystem

        mvp = MvpSystem()
        self._seed(mvp)
        prod = ProductionSystem(DSN, reset=True)
        self.addCleanup(prod.close)
        self._seed(prod)

        who = claims("T", "alice")
        mvp_order = [r.chunk.document_id for r in mvp.search(who, self.QUERY)]
        prod_order = [r.chunk.document_id for r in prod.search(who, self.QUERY)]
        self.assertEqual(mvp_order, ["d1", "d2", "d3", "d4"], "oracle ordering sanity")
        self.assertEqual(prod_order, mvp_order, "pgvector ranking must match the in-memory oracle order")

    def test_topk_does_not_truncate_before_acl(self) -> None:
        # A non-visible chunk (X, collection 'hid') ranks BETWEEN two visible ones (A>X>B by similarity).
        # With top_k=2 the correct ACL-then-top_k result is [A, B]; a SQL ``LIMIT 2`` before the ACL
        # filter would fetch [A, X], drop X, and wrongly return just [A].
        from raku_rag.production import ProductionSystem

        prod = ProductionSystem(DSN, reset=True)
        self.addCleanup(prod.close)
        prod.ingest_text(tenant_id="T", collection_id="vis", document_id="A",
                         text="turbine bearing vibration noise spectrum")
        prod.ingest_text(tenant_id="T", collection_id="hid", document_id="X",
                         text="turbine bearing vibration alignment")
        prod.ingest_text(tenant_id="T", collection_id="vis", document_id="B",
                         text="turbine bearing lubrication")
        prod.grant("T", ScopeType.COLLECTION, "vis", SubjectType.USER, "alice")

        who = claims("T", "alice")
        qvec = prod.embedder.embed([self.QUERY])[0]
        visible = prod.acl.visibility(who)
        results = prod.store.search("T", qvec, visible=visible, top_k=2)

        self.assertEqual([r.chunk.document_id for r in results], ["A", "B"])
        # the non-visible chunk is dropped AFTER ranking, BEFORE top_k — count reflects visible candidates.
        self.assertEqual(prod.store.last_prefiltered_count, 2)


if __name__ == "__main__":
    unittest.main()
