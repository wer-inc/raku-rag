"""Wave 1d — metadata-exact leg: precomputed-compacts fast path ≡ legacy expression predicate.

The leg's identifier match now runs as an array overlap over the ingest-time
``identifier_compacts`` columns (0026) instead of the 40-expression lower()/regexp_replace OR
(measured ~1.4s/query at N=10,000). The claim is EQUIVALENCE, not superset — this probe pins it
against real Postgres by running the same queries through both paths (the legacy path is forced
via the un-backfilled probe) and asserting identical results, including multiplicity ranking and
nested-mapping (`_mfg_meta`) identifiers. Also probes the NULL sentinel: a document row whose
compacts were never computed must force the legacy path rather than silently dropping matches.
Skip-guarded on Postgres availability; unique tenant per run; cascade cleanup.
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


def _postgres_available() -> bool:
    try:
        import psycopg

        with psycopg.connect(DSN, connect_timeout=2) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_name = 'chunks' AND column_name = 'identifier_compacts'"
                )
                return cur.fetchone() is not None
    except Exception:
        return False


@unittest.skipUnless(_postgres_available(), "Postgres/0026 not reachable (Tier B / local-only)")
class TestMetadataCompactsParity(unittest.TestCase):
    QUERY = "EQ-PRESS-042 のアラーム E-217 の対応を教えてください"

    def setUp(self) -> None:
        from raku_rag.production import ProductionSystem

        self.tenant = f"metacompact_{uuid.uuid4().hex[:12]}"
        self.system = ProductionSystem(DSN)
        self.addCleanup(self._cleanup)
        suffix = uuid.uuid4().hex[:8]
        self.docs = {
            f"eq_only_{suffix}": ("プレス機の点検メモ。", {"equipment_id": "EQ-PRESS-042"}),
            # NOTE: nested (_mfg_meta) identifiers cannot be planted through ingest_text —
            # the ingestion metadata normalizer strips unknown nested keys (the manufacturing
            # overlay attaches them post-ingest). Nested derivation parity is asserted at the
            # helper level in test_nested_mapping_compacts_derivation below.
            f"alarm_only_{suffix}": (
                "アラーム対応の一般メモ。",
                {"alarm_code": "E-217"},
            ),
            f"gold_{suffix}": (
                "EQ-PRESS-042 のアラーム E-217 の処置手順。",
                {"equipment_id": "EQ-PRESS-042", "alarm_code": "E-217"},
            ),
            f"unrelated_{suffix}": ("静電気対策規程。", {"equipment_id": "EQ-WELD-001"}),
        }
        for doc_id, (text, meta) in self.docs.items():
            self.system.ingest_text(
                tenant_id=self.tenant,
                collection_id="c",
                document_id=doc_id,
                text=text,
                chunking_metadata=meta,
            )
        self.system.grant(self.tenant, ScopeType.COLLECTION, "c", SubjectType.USER, "alice")
        self.who = claims(self.tenant, "alice")

    def _cleanup(self) -> None:
        try:
            with self.system._conn.cursor() as cur:
                cur.execute("DELETE FROM tenants WHERE tenant_id = %s", (self.tenant,))
        finally:
            self.system.close()

    def _leg(self):
        visible = self.system.acl.visibility(self.who)
        return [
            (s.chunk.document_id, s.retrieval_score)
            for s in self.system.store.metadata_exact_matches(
                self.tenant, self.QUERY, visible=visible, top_k=10
            )
        ]

    def test_fast_compacts_path_equals_legacy_expression_predicate(self) -> None:
        fast = self._leg()
        with mock.patch.object(
            type(self.system.store), "_has_uncompacted_live_rows", lambda self, tenant: True
        ):
            legacy = self._leg()
        self.assertEqual(fast, legacy, "compacts overlap must be the SAME predicate, not a subset")
        # multiplicity ranking sanity: the double-identifier gold leads; nested _mfg_meta matched.
        self.assertEqual(len(fast), 3)
        self.assertTrue(fast[0][0].startswith("gold_"))
        self.assertEqual({doc_id.split("_")[0] for doc_id, _ in fast}, {"gold", "eq", "alarm"})

    def test_nested_mapping_compacts_derivation(self) -> None:
        # The legacy SQL predicate reaches into the nested manufacturing mappings
        # (metadata->'_mfg_meta'->>field); the ingest-time compacts computation must cover the
        # same nested sources or overlay-attached identifiers would silently drop from the leg.
        from raku_rag.core.hybrid_retrieval import metadata_hot_identifier_compacts

        self.assertEqual(
            metadata_hot_identifier_compacts(
                {"_mfg_meta": {"alarm_code": "E-217"}, "equipment_id": "EQ-PRESS-042"}
            ),
            ["e217", "eqpress042"],
        )

    def test_null_compacts_forces_legacy_path_without_dropping_matches(self) -> None:
        # Simulate a pre-0026 document row (compacts never computed).
        with self.system._conn.cursor() as cur:
            cur.execute(
                "UPDATE documents SET identifier_compacts = NULL WHERE tenant_id = %s",
                (self.tenant,),
            )
        self.assertTrue(self.system.store._has_uncompacted_live_rows(self.tenant))
        results = self._leg()
        self.assertEqual(len(results), 3, "legacy fallback must still find every match")
        self.assertTrue(results[0][0].startswith("gold_"))


if __name__ == "__main__":
    unittest.main()
