"""Wave 1d — ACL correctness of the lexical SQL candidate pool (Postgres store).

The lexical leg now fetches only the top max(top_k*factor, min) candidates by directly-matched
query-term count, computed in SQL over the ingest-time ``lexical_token_hashes`` column (0026).
The SQL pool is ACL-BLIND — ACL stays the Python post-filter — so two failure modes must be
probed, mirroring the vector leg's over-fetch probes:

1. **Leak** — an ACL-hidden chunk must never be returned, whichever path (pool or fallback) ran.
2. **False negative** — when the truncated pool is saturated with ACL-hidden higher-match-count
   chunks, the visible lower-match chunk must still be returned via the exhaustive fallback.

Plus the un-backfilled sentinel: a live row with the '{}' hash default must force the exhaustive
path (pool ranks would be wrong), still returning exact results. Pool constants are patched on
``core.hybrid_retrieval`` (both stores read them through the module) to make a 5-chunk corpus
truncate the pool deterministically. Skip-guarded on Postgres availability; unique tenant per
run, no reset, rows purged on cleanup.
"""

from __future__ import annotations

import os
import unittest
import uuid
from unittest import mock

from raku_rag.domain.models import ScopeType, SubjectType
from tests.helpers import claims

DSN = os.environ.get(
    "BENCH_POSTGRES_URL",
    os.environ.get(
        "POSTGRES_URL",
        "postgresql://raku:raku@127.0.0.1:5432/raku_bench",  # pragma: allowlist secret -- local dev DB credential
    ),
)

_FACTOR = "raku_rag.core.hybrid_retrieval.LEXICAL_POOL_FACTOR"
_MIN = "raku_rag.core.hybrid_retrieval.LEXICAL_POOL_MIN"


def _postgres_available() -> bool:
    try:
        import psycopg

        with psycopg.connect(DSN, connect_timeout=2) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_name = 'chunks' AND column_name = 'lexical_token_hashes'"
                )
                return cur.fetchone() is not None
    except Exception:
        return False


@unittest.skipUnless(_postgres_available(), "Postgres/0026 not reachable (Tier B / local-only)")
class TestLexicalPoolAcl(unittest.TestCase):
    # HIDDEN docs share four query terms (high match count); the VISIBLE doc shares two (lower),
    # so every hidden chunk outranks the visible one in the SQL pool ordering.
    QUERY = "hydraulic actuator seal replacement torque"
    HIDDEN_TEXT = "hydraulic actuator seal replacement checklist item probe{n}"
    VISIBLE_TEXT = "hydraulic torque wrench storage cabinet rules"

    def setUp(self) -> None:
        from raku_rag.production import ProductionSystem

        self.tenant = f"lexpool_probe_{uuid.uuid4().hex[:12]}"
        self.system = ProductionSystem(DSN)
        self.addCleanup(self._cleanup)
        suffix = uuid.uuid4().hex[:8]  # document_id is a GLOBAL PK (0001): a reused id under a
        # new tenant conflicts with the old tenant's row, which RLS hides (fail-closed
        # InsufficientPrivilege on ingest) — so every run must mint fresh document ids.
        self.visible_doc = f"visible_{suffix}"
        self.hidden_docs = [f"hidden_{suffix}_{i}" for i in range(4)]
        for i, doc_id in enumerate(self.hidden_docs):
            self.system.ingest_text(
                tenant_id=self.tenant,
                collection_id="hidden",
                document_id=doc_id,
                text=self.HIDDEN_TEXT.format(n=i),
            )
        self.system.ingest_text(
            tenant_id=self.tenant,
            collection_id="vis",
            document_id=self.visible_doc,
            text=self.VISIBLE_TEXT,
        )
        self.system.grant(self.tenant, ScopeType.COLLECTION, "vis", SubjectType.USER, "alice")
        self.who = claims(self.tenant, "alice")

    def _cleanup(self) -> None:
        try:
            # Cascade-delete the probe tenant (collections/documents/chunks/grants follow via FK
            # ON DELETE CASCADE) so repeated runs leave nothing behind — crucially the documents
            # rows: purge() alone would leave them, and document_id is a GLOBAL PK.
            with self.system._conn.cursor() as cur:
                cur.execute("DELETE FROM tenants WHERE tenant_id = %s", (self.tenant,))
        finally:
            self.system.close()

    def _leg(self, top_k: int):
        visible = self.system.acl.visibility(self.who)
        return self.system.store.lexical_matches(
            self.tenant, self.QUERY, visible=visible, top_k=top_k
        )

    def test_pool_path_returns_only_acl_visible_chunks(self) -> None:
        # Default constants: pool covers the whole 5-chunk corpus (not truncated) — the pool path
        # itself answers. Only the visible chunk may come back.
        results = self._leg(top_k=5)
        self.assertEqual([r.chunk.document_id for r in results], [self.visible_doc])
        for r in results:
            self.assertNotIn(r.chunk.document_id, self.hidden_docs, "ACL-hidden chunk leaked")

    def test_truncated_hidden_pool_falls_back_and_rescues_visible_chunk(self) -> None:
        # Pool = max(1*1, 2) = 2 — saturated by the higher-match-count ACL-hidden chunks. A naive
        # truncated pool would return nothing; the ACL-drop fallback must rescue the visible
        # chunk (the false-negative failure mode).
        with mock.patch(_FACTOR, 1), mock.patch(_MIN, 2):
            results = self._leg(top_k=1)
        self.assertEqual(
            [r.chunk.document_id for r in results],
            [self.visible_doc],
            "truncated SQL pool contained only ACL-hidden chunks; the exhaustive fallback must "
            "still surface the visible chunk",
        )

    def test_truncated_pool_fallback_never_leaks(self) -> None:
        with mock.patch(_FACTOR, 1), mock.patch(_MIN, 2):
            results = self._leg(top_k=10)
        self.assertEqual([r.chunk.document_id for r in results], [self.visible_doc])
        for r in results:
            self.assertNotIn(r.chunk.document_id, self.hidden_docs, "ACL-hidden chunk leaked")

    def test_unbackfilled_rows_force_exact_exhaustive_path(self) -> None:
        # Simulate a pre-0026 row: clear one live chunk's hashes to the '{}' sentinel. The leg
        # must detect it and take the exhaustive path — same exact result, no wrong pool ranks.
        with self.system._conn.cursor() as cur:
            cur.execute(
                "UPDATE chunks SET lexical_token_hashes = '{}' WHERE tenant_id = %s "
                "AND document_id = %s",
                (self.tenant, self.hidden_docs[0]),
            )
        self.assertTrue(self.system.store._has_unhashed_live_rows(self.tenant))
        results = self._leg(top_k=5)
        self.assertEqual([r.chunk.document_id for r in results], [self.visible_doc])

    def test_pool_and_fallback_agree_for_fully_visible_corpus(self) -> None:
        # Give alice the hidden collection too: pool path (all visible) and forced-exhaustive
        # path must produce identical results — the fallback is a superset-exact re-derivation.
        self.system.grant(self.tenant, ScopeType.COLLECTION, "hidden", SubjectType.USER, "alice")
        pooled = [(r.chunk.document_id, round(r.retrieval_score, 12)) for r in self._leg(top_k=10)]
        with mock.patch.object(
            type(self.system.store), "_has_unhashed_live_rows", lambda self, tenant: True
        ):
            exhaustive = [
                (r.chunk.document_id, round(r.retrieval_score, 12)) for r in self._leg(top_k=10)
            ]
        self.assertEqual(pooled, exhaustive)
        self.assertEqual(len(pooled), 5, "all five chunks lexically match this query")


if __name__ == "__main__":
    unittest.main()
