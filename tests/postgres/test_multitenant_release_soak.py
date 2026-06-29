"""Tier B release soak: real Postgres, multiple tenants, and the core lifecycle.

This is the production-readiness release gate that Tier A cannot prove. It runs the same
``ProductionSystem`` boundary the deployed answer-service uses over real Postgres/pgvector/RLS, with
three tenants going through:

ingest -> search -> answer -> delete -> reindex

At every stage, citations/search results must remain tenant-local and a deleted document must not
reappear. The test is skip-safe without Postgres so the inner Tier-A loop stays stdlib-only.
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
class TestMultiTenantReleaseSoak(unittest.TestCase):
    RECORDS = (
        (
            "release_soak_tenant_a",
            "manuals_a",
            "doc_asset_a",
            "asset ASSET-A",
            "alpha-31",
        ),
        (
            "release_soak_tenant_b",
            "manuals_b",
            "doc_asset_b",
            "asset ASSET-B",
            "bravo-42",
        ),
        (
            "release_soak_tenant_c",
            "manuals_c",
            "doc_asset_c",
            "asset ASSET-C",
            "charlie-53",
        ),
    )

    def setUp(self) -> None:
        from raku_rag.production import ProductionSystem

        self.sys = ProductionSystem(DSN, reset=True)
        self.addCleanup(self.sys.close)

    def test_core_lifecycle_has_zero_cross_tenant_leaks(self) -> None:
        for tenant_id, collection_id, document_id, asset, value in self.RECORDS:
            self.sys.ingest_text(
                tenant_id=tenant_id,
                collection_id=collection_id,
                document_id=document_id,
                text=(
                    f"The calibration value for {asset} is {value}. "
                    "This shared maintenance marker appears in every tenant manual."
                ),
            )
            self.sys.grant(
                tenant_id,
                ScopeType.COLLECTION,
                collection_id,
                SubjectType.USER,
                self._user(tenant_id),
            )

        for tenant_id, _collection_id, document_id, asset, _value in self.RECORDS:
            self._assert_search_only_returns(tenant_id, document_id, "shared maintenance marker")
            self._assert_answer_only_cites(
                tenant_id,
                document_id,
                f"What is the calibration value for {asset}?",
            )

        deleted_tenant, _deleted_collection, deleted_doc, deleted_asset, _deleted_value = (
            self.RECORDS[1]
        )
        deletion = self.sys.deletion.delete(deleted_tenant, deleted_doc)
        self.assertGreaterEqual(deletion.tombstoned_chunks, 1)
        self.assertGreaterEqual(deletion.purged_chunks, 1)

        deleted_principal = claims(deleted_tenant, self._user(deleted_tenant))
        self.assertEqual(
            self.sys.search(deleted_principal, f"calibration value for {deleted_asset}"),
            [],
            "deleted tenant document must not reappear in search",
        )
        deleted_answer = self.sys.answer(
            deleted_principal, f"What is the calibration value for {deleted_asset}?"
        )
        self.assertEqual(deleted_answer.status, "insufficient_evidence")
        self.assertEqual(deleted_answer.used_chunks, ())

        # Remaining tenants still work, and the deleted tenant stays invisible to them.
        for tenant_id, _collection_id, document_id, asset, _value in (
            self.RECORDS[0],
            self.RECORDS[2],
        ):
            self._assert_answer_only_cites(
                tenant_id,
                document_id,
                f"What is the calibration value for {asset}?",
            )

        reindex_tenant, reindex_collection, reindex_doc, reindex_asset, old_value = self.RECORDS[2]
        new_value = "delta-64"
        plan = self.sys.reindex.reindex_documents(
            tenant_id=reindex_tenant,
            collection_id=reindex_collection,
            source_id="manuals",
            documents={
                reindex_doc: (
                    f"The calibration value for {reindex_asset} is {new_value}. "
                    "This document was rebuilt after an embedding model change."
                ).encode("utf-8")
            },
            reason="embedding_model_change",
            created_by="release-soak",
        )
        self.assertEqual(plan.status, "succeeded", plan.last_error)

        updated = self.sys.answer(
            claims(reindex_tenant, self._user(reindex_tenant)),
            f"What is the calibration value for {reindex_asset}?",
        )
        self.assertEqual(updated.status, "ok")
        self.assertTrue(updated.citations)
        self.assertTrue(all(c.document_id == reindex_doc for c in updated.citations))
        self.assertTrue(all(c.version == 2 for c in updated.citations))

        old_results = self.sys.search(
            claims(reindex_tenant, self._user(reindex_tenant)),
            f"calibration value {old_value}",
        )
        self.assertTrue(
            all(old_value not in r.chunk.text for r in old_results),
            "old version chunks must remain tombstoned after reindex switch",
        )

        for tenant_id, _collection_id, document_id, _asset, _value in self.RECORDS:
            if tenant_id == reindex_tenant:
                continue
            self._assert_search_does_not_return(tenant_id, reindex_doc, new_value)

    def _assert_search_only_returns(self, tenant_id: str, document_id: str, query: str) -> None:
        results = self.sys.search(claims(tenant_id, self._user(tenant_id)), query)
        self.assertTrue(results, f"{tenant_id} should see its own release-soak document")
        self.assertTrue(all(r.chunk.tenant_id == tenant_id for r in results))
        self.assertEqual({r.chunk.document_id for r in results}, {document_id})
        self.assertEqual(
            self.sys.store.last_prefiltered_count,
            1,
            "real PG soak should pre-filter to the current tenant's visible live chunk only",
        )

    def _assert_search_does_not_return(
        self, tenant_id: str, forbidden_document_id: str, query: str
    ) -> None:
        results = self.sys.search(claims(tenant_id, self._user(tenant_id)), query)
        self.assertNotIn(forbidden_document_id, {r.chunk.document_id for r in results})
        self.assertTrue(all(r.chunk.tenant_id == tenant_id for r in results))

    def _assert_answer_only_cites(self, tenant_id: str, document_id: str, query: str) -> None:
        answer = self.sys.answer(claims(tenant_id, self._user(tenant_id)), query)
        self.assertEqual(answer.status, "ok", answer.text)
        self.assertTrue(answer.citations)
        self.assertTrue(all(c.document_id == document_id for c in answer.citations))

    def _user(self, tenant_id: str) -> str:
        return f"user_{tenant_id}"


if __name__ == "__main__":
    unittest.main()
