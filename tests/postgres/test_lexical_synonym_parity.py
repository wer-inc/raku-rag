"""Wave 1c — lexical-leg synonym expansion parity (in-memory oracle vs Postgres).

Both stores forward the ``expansions`` argument to the SHARED ``lexical_match_score``, so a drift
here would silently expand synonyms on one backend only (Tier A green, deployed store blind — the
exact failure mode the multiplicity parity test guards for the metadata leg). Skip-guarded on
Postgres availability (Tier B / local-only), same as test_hybrid_multiplicity_parity.
"""

from __future__ import annotations

import os
import unittest

from raku_rag.core.hybrid_retrieval import synonym_expansions
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
class TestLexicalSynonymParity(unittest.TestCase):
    QUERY = "搬送コンベアの減速機でオイルリークが起きた場合の点検を教えてください。"
    GROUPS = {"油漏れ": ("オイルリーク",)}
    # gold carries the canonical form (油漏れ) the query's synonym (オイルリーク) maps to; the
    # distractor shares the family/component vocabulary and covers MORE of the query directly
    # (場合), so without expansion it outranks the gold — with expansion the order flips. A third
    # unrelated doc must stay unaffected by expansion on both backends.
    DOCS = [
        (
            "d_gold",
            "搬送コンベアの減速機で油漏れが発生した時の点検手順: シールパッキンを交換する。",
        ),
        (
            "d_distractor",
            "搬送コンベアの減速機で異常振動が発生した場合の点検手順: 取付ボルトを確認する。",
        ),
        ("d_unrelated", "静電気対策規程: 作業者はリストストラップを着用する。"),
    ]

    def _seed(self, sys) -> None:
        for doc_id, text in self.DOCS:
            sys.ingest_text(tenant_id="T", collection_id="c", document_id=doc_id, text=text)
        sys.grant("T", ScopeType.COLLECTION, "c", SubjectType.USER, "alice")

    def _leg(self, sys, expansions):
        visible = sys.acl.visibility(claims("T", "alice"))
        return sys.store.lexical_matches(
            "T", self.QUERY, visible=visible, top_k=10, expansions=expansions
        )

    def test_expanded_lexical_leg_matches_in_memory_oracle(self) -> None:
        from raku_rag.app import MvpSystem
        from raku_rag.production import ProductionSystem

        expansions = synonym_expansions(self.QUERY, self.GROUPS)
        self.assertTrue(expansions)

        mvp = MvpSystem()
        self._seed(mvp)
        prod = ProductionSystem(DSN, reset=True)
        self.addCleanup(prod.close)
        self._seed(prod)

        for label, sys_ in (("in-memory", mvp), ("postgres", prod)):
            with self.subTest(store=label):
                unexpanded = [(s.chunk.document_id, s.retrieval_score) for s in self._leg(sys_, ())]
                expanded = [
                    (s.chunk.document_id, s.retrieval_score) for s in self._leg(sys_, expansions)
                ]
                # oracle behavior on BOTH backends: distractor first without expansion, gold
                # first with it; the unrelated doc's score is identical in both conditions.
                self.assertEqual(unexpanded[0][0], "d_distractor")
                self.assertEqual(expanded[0][0], "d_gold")
                self.assertEqual(
                    dict(unexpanded).get("d_unrelated"), dict(expanded).get("d_unrelated")
                )

        mvp_leg = [
            (s.chunk.document_id, round(s.retrieval_score, 12)) for s in self._leg(mvp, expansions)
        ]
        prod_leg = [
            (s.chunk.document_id, round(s.retrieval_score, 12)) for s in self._leg(prod, expansions)
        ]
        self.assertEqual(
            prod_leg, mvp_leg, "Postgres expanded lexical leg must match the in-memory oracle"
        )


if __name__ == "__main__":
    unittest.main()
