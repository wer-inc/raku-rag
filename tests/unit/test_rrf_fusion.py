"""Wave 1b — Reciprocal Rank Fusion for the hybrid retrieval merge.

Pins the fix for the measured scale defect (docs/product/scale-bench.md): the union-with-max-score
merge left the metadata leg's flat ``METADATA_EXACT_MATCH_SCORE`` ties to degenerate to chunk
position/chunk_id order, so at 10k documents a chunk matching BOTH query identifiers tied with
chunks matching only one (identifier recall@5 1.0@300 → 0.417@10k). The ordering contract now
(the measured winner of the bench strategy grid — see ``_merge_hybrid_results``):

1. absolute score + query-plan boosts (unchanged coarse bands: identifier-exact > lexical > vector);
2. metadata-leg rank — the leg ranks by identifier match MULTIPLICITY (both stores);
3. RRF (Σ 1/(RRF_K + rank_in_leg)) across the three legs;
4. chunk_id.

``retrieval_score`` stays the MAX absolute leg score — the rank signals are ordering-only, so the
groundedness pre-gate (``QueryProfile.score_threshold``) and the no-answer refusal semantics are
unchanged, and the deterministic ``ScoreOrderReranker`` preserves retrieval order. Leg-level fixes
pinned here too: the lexical scorer weighs verbatim identifier mentions and demotes recency to a
tie-breaker; ``part_no`` is a hot identifier field.
"""

from __future__ import annotations

import unittest

from raku_rag.app import MvpSystem
from raku_rag.core.hybrid_retrieval import (
    _text_identifier_match_count,
    LEXICAL_MATCH_MAX_SCORE,
    lexical_match_score,
    METADATA_EXACT_MATCH_SCORE,
    metadata_identifier_match_count,
    query_identifiers,
)
from raku_rag.core.query_planner import plan_query
from raku_rag.core.security.acl import AclPolicy
from raku_rag.domain.models import (
    ACLGrant,
    Chunk,
    IdentityClaims,
    QueryProfile,
    ScopeType,
    ScoredChunk,
    SubjectType,
)
from raku_rag.providers.embeddings import HashingEmbeddingProvider
from raku_rag.providers.rerankers import ScoreOrderReranker
from raku_rag.providers.vectorstores import InMemoryVectorStore
from raku_rag.services.retrieval import (
    _apply_query_plan_boosts,
    _HybridRanks,
    _merge_hybrid_results,
    RetrievalService,
    RRF_K,
)

T = "rrf_tenant"


def _chunk(
    chunk_id: str, *, position: int = 0, metadata: dict | None = None, text: str = "t"
) -> Chunk:
    return Chunk(
        tenant_id=T,
        chunk_id=chunk_id,
        document_id=chunk_id.split(":")[0],
        collection_id="c",
        text=text,
        position=position,
        metadata=metadata or {},
    )


def _scored(chunk_id: str, score: float, **kwargs) -> ScoredChunk:
    return ScoredChunk(chunk=_chunk(chunk_id, **kwargs), retrieval_score=score)


class TestRrfMerge(unittest.TestCase):
    def test_score_bands_stay_primary_rrf_breaks_ties_inside(self) -> None:
        # The metadata-exact band (1.25) stays above lexical/vector regardless of cross-leg
        # agreement (measured: equal-weight RRF across bands collapsed multi_doc recall 1.0→0.32).
        # WITHIN an equal-score band, cross-leg RRF decides: "both" (rank 1 in lexical AND
        # vector) precedes "lexonly" (rank 2 in lexical only) despite equal absolute scores.
        lexical = [_scored("both:0", 0.9), _scored("lexonly:0", 0.9)]
        vector = [_scored("both:0", 0.5), _scored("vec2:0", 0.4)]
        metadata = [_scored("single:0", METADATA_EXACT_MATCH_SCORE)]

        merged, ranks = _merge_hybrid_results(metadata, lexical, vector)

        self.assertEqual(
            [s.chunk.chunk_id for s in merged],
            ["single:0", "both:0", "lexonly:0", "vec2:0"],
        )
        # RRF sanity: two rank-1 appearances for the cross-leg chunk.
        self.assertAlmostEqual(ranks.rrf_by_id["both:0"], 2.0 / (RRF_K + 1))
        self.assertAlmostEqual(ranks.rrf_by_id["single:0"], 1.0 / (RRF_K + 1))
        self.assertEqual(ranks.meta_rank_by_id, {"single:0": 1})

    def test_retrieval_score_stays_max_absolute_leg_score(self) -> None:
        # Ordering carries the rank signals, but the score every downstream absolute-scale
        # consumer sees (groundedness pre-gate score_threshold, answer confidence) is still the
        # max leg score.
        metadata = [_scored("dup:0", METADATA_EXACT_MATCH_SCORE)]
        lexical = [_scored("dup:0", 0.8)]

        merged, _ranks = _merge_hybrid_results(metadata, lexical, [])

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].retrieval_score, METADATA_EXACT_MATCH_SCORE)

    def test_metadata_leg_rank_precedes_rrf_inside_the_flat_band(self) -> None:
        # Inside the flat 1.25 band, the metadata leg's own rank (= identifier multiplicity from
        # the stores) wins even against stronger cross-leg agreement of a lower-multiplicity doc.
        metadata = [
            _scored("gold:0", METADATA_EXACT_MATCH_SCORE),  # leg rank 1 (matched both ids)
            _scored("crowd:0", METADATA_EXACT_MATCH_SCORE),  # leg rank 2 (matched one id)
        ]
        lexical = [_scored("crowd:0", 0.9)]  # crowd also lexical rank 1 => higher RRF
        vector = [_scored("crowd:0", 0.5)]

        merged, ranks = _merge_hybrid_results(metadata, lexical, vector)

        self.assertGreater(ranks.rrf_by_id["crowd:0"], ranks.rrf_by_id["gold:0"])
        self.assertEqual([s.chunk.chunk_id for s in merged][:2], ["gold:0", "crowd:0"])

    def test_equal_band_equal_rrf_falls_back_to_chunk_id(self) -> None:
        equal_a = [_scored("b-second:0", 0.7)]
        equal_b = [_scored("a-first:0", 0.7)]
        merged_equal, _ranks = _merge_hybrid_results([], equal_a, equal_b)
        self.assertEqual([s.chunk.chunk_id for s in merged_equal], ["a-first:0", "b-second:0"])


class TestIdentifierMatchMultiplicity(unittest.TestCase):
    def test_count_dedupes_normalized_and_compact_twins(self) -> None:
        # query_identifiers emits BOTH "eq-press-042" and "eqpress042" for one physical
        # identifier; the count must treat them as ONE match.
        identifiers = query_identifiers("EQ-PRESS-042 のアラーム E-217 は?")
        self.assertGreaterEqual(len(identifiers), 4)

        one = metadata_identifier_match_count({"equipment_id": "EQ-PRESS-042"}, identifiers)
        both = metadata_identifier_match_count(
            {"equipment_id": "EQ-PRESS-042", "alarm_code": "E-217"}, identifiers
        )
        none = metadata_identifier_match_count({"equipment_id": "EQ-OTHER-999"}, identifiers)

        self.assertEqual(one, 1)
        self.assertEqual(both, 2)
        self.assertEqual(none, 0)

    def test_metadata_leg_ranks_by_multiplicity_before_position(self) -> None:
        store = InMemoryVectorStore()
        gold = _chunk(
            "gold:0",
            position=9,  # later position: under the old (position, chunk_id) sort it lost
            metadata={"equipment_id": "EQ-PRESS-042", "alarm_code": "E-217"},
        )
        same_equipment = _chunk("eqonly:0", position=0, metadata={"equipment_id": "EQ-PRESS-042"})
        same_alarm = _chunk("alarmonly:0", position=1, metadata={"alarm_code": "E-217"})
        store.upsert([(gold, [0.0, 1.0]), (same_equipment, [0.0, 1.0]), (same_alarm, [0.0, 1.0])])

        matches = store.metadata_exact_matches(
            T, "EQ-PRESS-042 のアラーム E-217 は?", visible=lambda c: True, top_k=10
        )

        self.assertEqual([s.chunk.chunk_id for s in matches], ["gold:0", "eqonly:0", "alarmonly:0"])
        # The score stays flat: multiplicity is expressed as leg RANK, not as a score change.
        self.assertEqual({s.retrieval_score for s in matches}, {METADATA_EXACT_MATCH_SCORE})

    def test_part_no_is_a_hot_identifier_field(self) -> None:
        # Part numbers are exact business identifiers (交換部品の型番指名); the metadata leg must
        # see them like equipment ids / alarm codes.
        identifiers = query_identifiers("交換した部品 PN-10817 の対策内容は?")
        count = metadata_identifier_match_count({"part_no": "PN-10817"}, identifiers)
        self.assertEqual(count, 1)


class TestLexicalIdentifierWeight(unittest.TestCase):
    """Wave 1b leg fix: a query identifier appearing VERBATIM in the text must dominate prose
    overlap — measured at scale, the coverage edge of containing the queried doc number (~0.023)
    was smaller than the recency boost (0.09), so the one true document fell out of the leg.
    """

    def test_verbatim_identifier_mention_outranks_newer_boilerplate(self) -> None:
        query = "点検基準書 INS-0435 の判定基準を教えてください。"
        gold = (
            "点検基準書 INS-0435。対象設備:射出成形機。点検項目:金型の摩耗。判定基準:0.05mm 以下。"
        )
        crowd = (
            "点検基準書 INS-0999。対象設備:プレス機。点検項目:ベルトの摩耗。判定基準:0.1mm 以下。"
        )

        gold_score = lexical_match_score(query, gold)
        # The crowd doc gets the maximum recency boost (fresh effective_date); the identifier
        # weight must still dominate it.
        crowd_score = lexical_match_score(query, crowd, {"effective_date": "2026-07-01"})

        self.assertGreater(gold_score, crowd_score)
        self.assertGreater(
            gold_score - crowd_score, 0.05, "identifier weight must exceed recency-boost noise"
        )
        # And the leg cap keeps lexical identifier mentions below the metadata-exact band.
        self.assertLessEqual(gold_score, LEXICAL_MATCH_MAX_SCORE)
        self.assertLess(LEXICAL_MATCH_MAX_SCORE, METADATA_EXACT_MATCH_SCORE)

    def test_identifier_free_queries_get_no_identifier_weight(self) -> None:
        query = "めっき部品のキズ、打痕、バリの合否判定しきい値を短く整理して"
        text = "外観欠陥判定基準書。キズは長さ0.5mm以下、打痕は直径0.3mm以下を合格とする。"
        self.assertEqual(_text_identifier_match_count(query, text), 0)
        self.assertGreater(lexical_match_score(query, text), 0.7)  # prose scoring unchanged


class TestEndToEndOrdering(unittest.TestCase):
    """The scale defect in miniature, through the full RetrievalService + ScoreOrderReranker.

    Uses the real deterministic hashing embedder so the vector leg reflects the texts (as at the
    measured bench) instead of a degenerate all-equal-cosine tie.
    """

    def _retrieve(self, store: InMemoryVectorStore, embedder, query: str, top_k: int = 5):
        acl = AclPolicy([ACLGrant(T, ScopeType.COLLECTION, "c", SubjectType.USER, "alice")])
        service = RetrievalService(store, embedder, acl, ScoreOrderReranker())
        profile = QueryProfile(top_k=top_k, rerank_enabled=True, rerank_top_n=10)
        return service.retrieve(
            IdentityClaims(tenant_id=T, user_id="alice"), query, profile, correlation_id="rrf-e2e"
        )

    def test_both_identifier_match_beats_flat_tie_crowd(self) -> None:
        # The measured defect shape (scale-bench 結果3): gold matches BOTH query identifiers, a
        # crowd of docs (here 6 > top_k) each match ONE — all flat 1.25 + the same +0.02 boost.
        # Under union-max the tie degenerated to position order and gold (late position) fell out
        # of top_k entirely; under RRF gold's leg ranks (multiplicity + lexical + vector) win.
        embedder = HashingEmbeddingProvider()
        store = InMemoryVectorStore()
        items: list[tuple[Chunk, list[float]]] = []
        for i in range(6):
            text = f"設備{i}号機のアラーム E-217 対応メモ。リセット後に再起動する。"
            items.append(
                (
                    _chunk(f"d{i}:0", position=i, metadata={"alarm_code": "E-217"}, text=text),
                    embedder.embed([text])[0],
                )
            )
        gold_text = "EQ-PRESS-042 のアラーム E-217 の処置手順。冷却水流量を確認する。"
        gold = _chunk(
            "gold:0",
            position=99,
            metadata={"equipment_id": "EQ-PRESS-042", "alarm_code": "E-217"},
            text=gold_text,
        )
        items.append((gold, embedder.embed([gold_text])[0]))
        store.upsert(items)

        result = self._retrieve(store, embedder, "EQ-PRESS-042 のアラーム E-217 の対応は?")

        self.assertEqual(result[0].chunk.chunk_id, "gold:0")
        # Score scale unchanged: the winner still carries the absolute metadata-leg score
        # (plus absolute query-plan boosts), well above QueryProfile.score_threshold.
        self.assertGreaterEqual(result[0].retrieval_score, METADATA_EXACT_MATCH_SCORE)

    def test_unanswerable_identifier_query_still_refused(self) -> None:
        # No-answer gate semantics must survive RRF: scores are unchanged, so a question about
        # equipment that does not exist keeps refusing (score threshold + salient gate).
        system = MvpSystem()
        system.grant(T, ScopeType.COLLECTION, "c", SubjectType.USER, "alice")
        system.ingest_text(
            tenant_id=T,
            collection_id="c",
            document_id="doc-1",
            text="EQ-PRESS-042 のアラーム E-217 は温度異常を示す。冷却水流量を確認する。",
            chunking_metadata={"equipment_id": "EQ-PRESS-042", "alarm_code": "E-217"},
        )
        who = IdentityClaims(tenant_id=T, user_id="alice")

        answered = system.answer(who, "EQ-PRESS-042 のアラーム E-217 は何を示しますか。")
        refused = system.answer(who, "EQ-ROBOT-999 のアラーム E-901 の解除手順を教えてください。")

        self.assertEqual(answered.status, "ok")
        self.assertEqual(refused.status, "insufficient_evidence")


class TestBoostInteraction(unittest.TestCase):
    def test_boosts_stay_absolute_and_reband_hinted_chunks(self) -> None:
        plan = plan_query("ポンプの点検手順を教えて")  # intent=procedure => document_kind hint
        self.assertIn("document_kind", plan.filter_hints)
        tied_a = _scored("a:0", 0.8, metadata={"document_kind": "quality_report"})
        tied_b = _scored("b:0", 0.8, metadata={"document_kind": "quality_report"})
        hinted = _scored("hint:0", 0.8, metadata={"document_kind": "work_instruction"})
        ranks = _HybridRanks({}, {"a:0": 1.0 / 61, "b:0": 1.0 / 61, "hint:0": 1.0 / 61})

        boosted = _apply_query_plan_boosts([tied_a, tied_b, hinted], plan, ranks)

        # The +0.06 document_kind boost lifts the hinted chunk into a higher score band; equal
        # bands with equal RRF fall back to chunk_id.
        self.assertEqual([s.chunk.chunk_id for s in boosted], ["hint:0", "a:0", "b:0"])
        # The boost VALUE is an absolute-score addition (scale-compatible with score_threshold).
        self.assertAlmostEqual(boosted[0].retrieval_score, 0.86)
        self.assertAlmostEqual(boosted[1].retrieval_score, 0.8)

    def test_rrf_breaks_ties_within_an_equal_boosted_band(self) -> None:
        # Same boosted score for both chunks; cross-leg agreement (higher RRF) decides — this is
        # the replacement for the old arbitrary insertion/position tie order.
        plan = plan_query("ポンプの点検手順を教えて")
        first = _scored("zz-agree:0", 0.9, metadata={"document_kind": "quality_report"})
        second = _scored("aa-single:0", 0.9, metadata={"document_kind": "quality_report"})
        ranks = _HybridRanks({}, {"zz-agree:0": 2.0 / 61, "aa-single:0": 1.0 / 61})

        boosted = _apply_query_plan_boosts([second, first], plan, ranks)

        self.assertEqual([s.chunk.chunk_id for s in boosted], ["zz-agree:0", "aa-single:0"])

    def test_metadata_leg_rank_precedes_rrf_after_boosts(self) -> None:
        # Within the flat metadata band (equal boosted scores), leg rank (multiplicity) wins over
        # RRF — "ties broken by multiplicity" survives the boost pass.
        plan = plan_query("ポンプの点検手順を教えて")
        gold = _scored("gold:0", 1.25, metadata={"document_kind": "quality_report"})
        crowd = _scored("crowd:0", 1.25, metadata={"document_kind": "quality_report"})
        ranks = _HybridRanks(
            {"gold:0": 1, "crowd:0": 2},
            {"gold:0": 1.0 / 61, "crowd:0": 3.0 / 61},  # crowd has stronger cross-leg agreement
        )

        boosted = _apply_query_plan_boosts([gold, crowd], plan, ranks)

        self.assertEqual([s.chunk.chunk_id for s in boosted], ["gold:0", "crowd:0"])

    def test_vector_only_path_keeps_absolute_boosted_score_order(self) -> None:
        # No hybrid legs => no rank signals => unchanged pre-1b behavior: sort by boosted score.
        plan = plan_query("ポンプの点検手順を教えて")
        low_hinted = _scored("hint:0", 0.79, metadata={"document_kind": "work_instruction"})
        high_plain = _scored("plain:0", 0.8, metadata={"document_kind": "quality_report"})

        boosted = _apply_query_plan_boosts([high_plain, low_hinted], plan)

        self.assertEqual([s.chunk.chunk_id for s in boosted], ["hint:0", "plain:0"])
        self.assertAlmostEqual(boosted[0].retrieval_score, 0.85)


if __name__ == "__main__":
    unittest.main()
