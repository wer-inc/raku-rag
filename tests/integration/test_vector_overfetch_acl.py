"""Wave 1d — ACL correctness of the HNSW LIMIT + over-fetch vector leg.

The vector leg now ranks with an indexed ``ORDER BY embedding <=> q LIMIT over_fetch`` so the HNSW
index is used instead of a full sequential scan. ACL is still a Python POST-filter (never in SQL),
so a naive ``LIMIT k`` would be unsafe two ways:

1. **Leak** — it must NEVER surface a chunk the principal lacks ACL for (cross-scope leak).
2. **False negative** — it must NEVER silently drop a chunk the principal CAN see, even when the
   nearest ``over_fetch`` window is saturated with higher-similarity chunks the principal cannot
   see. That case must fall back to the exhaustive (exact, pre-1d) scan.

Both are driven against a real Postgres here. The over-fetch constants are patched down so a tiny
corpus deterministically saturates the window and forces the exhaustive fallback; a separate probe
patches them so the window covers the corpus and the LIMIT path itself answers without fallback.
The ranking precondition (every ACL-hidden chunk outranks the visible one) is asserted explicitly
so the probes cannot silently pass for the wrong reason. Skip-guarded on Postgres availability
(Tier B / local-only). A UNIQUE tenant per run, no database reset — safe next to other corpora
(RLS + tenant scoping isolate the probe rows), and rows are purged on cleanup.
"""

from __future__ import annotations

import os
import unittest
import uuid
from unittest import mock

from raku_rag.domain.models import ScopeType, SubjectType
from tests.helpers import claims

# A dedicated DB (never raku_parity — Tier-B suites TRUNCATE it mid-run elsewhere): the bench DB by
# default, overridable for CI/gate environments.
DSN = os.environ.get(
    "BENCH_POSTGRES_URL",
    os.environ.get(
        "POSTGRES_URL",
        "postgresql://raku:raku@127.0.0.1:5432/raku_bench",  # pragma: allowlist secret -- local dev DB credential
    ),
)

_FACTOR = "raku_rag.persistence.postgres._VECTOR_OVERFETCH_FACTOR"
_MIN = "raku_rag.persistence.postgres._VECTOR_OVERFETCH_MIN"


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
class TestVectorOverfetchAcl(unittest.TestCase):
    # The HIDDEN docs share five query tokens (high cosine); the VISIBLE doc shares one (low
    # cosine) — so every hidden chunk ranks strictly above the visible chunk by distance.
    QUERY = "alpha beta gamma delta epsilon"
    HIDDEN_TEXT = "alpha beta gamma delta epsilon zeta signal probe{n}"
    VISIBLE_TEXT = "alpha lonely unrelated filler words only"

    def setUp(self) -> None:
        from raku_rag.production import ProductionSystem

        self.tenant = f"acl_probe_{uuid.uuid4().hex[:12]}"
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
        # alice can read ONLY the "vis" collection — every "hidden" chunk is ACL-invisible to her.
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

    def _search(self, top_k: int, *, everything: bool = False):
        qvec = self.system.embedder.embed([self.QUERY])[0]
        visible = (lambda chunk: True) if everything else self.system.acl.visibility(self.who)
        return self.system.store.search(self.tenant, qvec, visible=visible, top_k=top_k)

    def test_precondition_hidden_chunks_outrank_the_visible_one(self) -> None:
        # The probes below depend on the ACL-hidden chunks dominating the similarity window; pin
        # that ordering so the fallback probes cannot pass vacuously.
        order = [r.chunk.document_id for r in self._search(top_k=5, everything=True)]
        self.assertEqual(order[-1], self.visible_doc)
        self.assertEqual(set(order[:-1]), set(self.hidden_docs))

    def test_limit_window_path_returns_only_acl_visible_chunks(self) -> None:
        # Window (6) covers the whole 5-chunk corpus and yields >= top_k (1) visible chunks, so the
        # LIMIT path itself answers (no fallback): it must return the visible chunk and nothing
        # ACL-hidden, in spite of 4 hidden chunks ranking above it inside the window.
        with mock.patch(_FACTOR, 2), mock.patch(_MIN, 6):
            results = self._search(top_k=1)
        self.assertEqual([r.chunk.document_id for r in results], [self.visible_doc])
        for r in results:
            self.assertNotIn(r.chunk.document_id, self.hidden_docs, "ACL-hidden chunk leaked")

    def test_exhaustive_fallback_rescues_visible_chunk_past_a_hidden_window(self) -> None:
        # Window (max(1*1, 2) = 2) is saturated by higher-similarity ACL-hidden chunks — a naive
        # LIMIT would return nothing. The visible-count fallback must rescue the visible chunk:
        # silently dropping it would be the false-negative failure mode.
        with mock.patch(_FACTOR, 1), mock.patch(_MIN, 2):
            results = self._search(top_k=1)
        self.assertEqual(
            [r.chunk.document_id for r in results],
            [self.visible_doc],
            "over-fetch window was exhausted by ACL-hidden chunks; the exhaustive fallback must "
            "still surface the visible chunk (no false negative)",
        )
        # The fallback path scanned exhaustively: the count is the exact visible total.
        self.assertEqual(self.system.store.last_prefiltered_count, 1)

    def test_fallback_path_never_leaks_hidden_chunks(self) -> None:
        # Same forced-fallback conditions, asking for more than exist: still only the visible one.
        with mock.patch(_FACTOR, 1), mock.patch(_MIN, 2):
            results = self._search(top_k=10)
        self.assertEqual([r.chunk.document_id for r in results], [self.visible_doc])
        for r in results:
            self.assertNotIn(r.chunk.document_id, self.hidden_docs, "ACL-hidden chunk leaked")

    def test_default_constants_end_to_end(self) -> None:
        # Unpatched production constants (window = max(5*20, 200)): identical ACL outcome.
        results = self._search(top_k=5)
        self.assertEqual([r.chunk.document_id for r in results], [self.visible_doc])
        self.assertEqual(self.system.store.last_prefiltered_count, 1)


if __name__ == "__main__":
    unittest.main()
