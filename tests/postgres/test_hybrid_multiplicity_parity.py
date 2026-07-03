"""Wave 1b — metadata-exact leg multiplicity ranking parity (in-memory oracle vs Postgres).

The metadata identifier leg now ranks by match MULTIPLICITY (distinct query identifiers matched)
before Reciprocal Rank Fusion. Both stores must produce the same leg order — a drift here silently
re-opens the flat-1.25 tie degeneration measured in docs/product/scale-bench.md on one backend
only. Skip-guarded on Postgres availability (Tier B / local-only), same as test_ranking_parity.
"""

from __future__ import annotations

import os
import unittest

from raku_rag.core.hybrid_retrieval import METADATA_EXACT_MATCH_SCORE
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
class TestHybridMultiplicityParity(unittest.TestCase):
    QUERY = "EQ-PRESS-042 のアラーム E-217 の対応を教えてください"
    # gold matches BOTH query identifiers; the others one each. Ingest order puts gold LAST so a
    # position/chunk_id ordering (the pre-1b behavior) would rank it last inside the flat band.
    DOCS = [
        ("eq_only", "プレス機の点検メモ。", {"equipment_id": "EQ-PRESS-042"}),
        ("alarm_only", "アラーム対応の一般メモ。", {"alarm_code": "E-217"}),
        (
            "gold",
            "EQ-PRESS-042 のアラーム E-217 の処置手順。",
            {"equipment_id": "EQ-PRESS-042", "alarm_code": "E-217"},
        ),
    ]

    def _seed(self, sys) -> None:
        for doc_id, text, meta in self.DOCS:
            sys.ingest_text(
                tenant_id="T",
                collection_id="c",
                document_id=doc_id,
                text=text,
                chunking_metadata=meta,
            )
        sys.grant("T", ScopeType.COLLECTION, "c", SubjectType.USER, "alice")

    def _leg_order(self, sys) -> list[str]:
        who = claims("T", "alice")
        visible = sys.acl.visibility(who)
        leg = sys.store.metadata_exact_matches("T", self.QUERY, visible=visible, top_k=10)
        self.assertEqual({s.retrieval_score for s in leg}, {METADATA_EXACT_MATCH_SCORE})
        return [s.chunk.document_id for s in leg]

    def test_multiplicity_leg_order_matches_in_memory_oracle(self) -> None:
        from raku_rag.app import MvpSystem
        from raku_rag.production import ProductionSystem

        mvp = MvpSystem()
        self._seed(mvp)
        prod = ProductionSystem(DSN, reset=True)
        self.addCleanup(prod.close)
        self._seed(prod)

        mvp_order = self._leg_order(mvp)
        prod_order = self._leg_order(prod)
        self.assertEqual(
            mvp_order,
            ["gold", "alarm_only", "eq_only"],
            "oracle: multiplicity (2 identifiers) outranks single matches despite later "
            "position; equal counts fall back to position/chunk_id",
        )
        self.assertEqual(
            prod_order, mvp_order, "Postgres metadata leg must match the in-memory oracle order"
        )


if __name__ == "__main__":
    unittest.main()
