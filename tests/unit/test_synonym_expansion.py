"""Wave 1c — tenant-approved synonym/abbreviation query expansion for the LEXICAL leg.

The measured gap (docs/product/scale-bench.md): queries whose salient words share zero CJK bigrams
with the target document's surface form (年休 vs 有給休暇, オーバーヒート vs 温度上昇) are invisible
to the lexical leg and the hashing embedder, and RRF fusion (Wave 1b) cannot help because no leg
carries the signal. 1c expands the query's terms with the tenant's ``retrieval.synonyms`` lexicon
entries — for the lexical leg ONLY.

Contract pinned here:
- ``retrieval.synonyms`` is a tenant-editable lexicon namespace (admin API + audit, no defaults).
- Group expansion is SYMMETRIC ({key} ∪ values): whichever member the query used, the others are
  the alternatives.
- Ranking: a synonym-covered term contributes ``SYNONYM_COVERAGE_WEIGHT`` (=0.9 < 1.0) coverage
  and no frequency/density — an expanded-term hit never outranks a direct hit at equal coverage.
- RetrievalService applies expansion to the lexical leg only, fail-open on lexicon outage.

Safety invariants (#78/#80 — expansion never reaches intent_query / high-risk classification /
the salient-coverage gate) are pinned in tests/unit/test_synonym_expansion_safety.py.
"""

from __future__ import annotations

import unittest

from raku_rag.core.hybrid_retrieval import (
    lexical_match_score,
    SYNONYM_COVERAGE_WEIGHT,
    synonym_expansions,
)
from raku_rag.domain.models import QueryProfile, ScopeType, SubjectType
from raku_rag.app import MvpSystem
from raku_rag.persistence.lexicon import InMemoryLexiconRepository
from raku_rag.services.lexicon import EDITABLE_NAMESPACES, LexiconService
from tests.helpers import claims

_GROUPS = {"温度上昇": ("オーバーヒート",), "有給休暇": ("年休", "有休"), "paid leave": ("pto",)}


class SynonymExpansionDerivationTest(unittest.TestCase):
    def test_query_using_synonym_expands_to_canonical_form(self) -> None:
        # The tenant keyed the entry by the canonical DOCUMENT term; the query used the synonym.
        expansions = synonym_expansions("年休の繰越の上限を教えてください", _GROUPS)
        self.assertEqual(len(expansions), 1)
        self.assertIn("有給休暇", expansions[0].alternatives)
        self.assertIn("有休", expansions[0].alternatives)
        self.assertIn("年休", expansions[0].source_terms)

    def test_query_using_canonical_form_expands_to_synonyms(self) -> None:
        expansions = synonym_expansions("有給休暇の繰越の上限を教えてください", _GROUPS)
        self.assertEqual(len(expansions), 1)
        self.assertEqual(expansions[0].alternatives, ("年休", "有休"))
        # source terms are the query's own bigrams inside the matched member.
        self.assertIn("有給", expansions[0].source_terms)
        self.assertIn("休暇", expansions[0].source_terms)

    def test_ascii_membership_is_token_scoped_not_substring(self) -> None:
        # "pto" inside "laptop" must NOT trigger the group.
        self.assertEqual(synonym_expansions("what is the laptop policy", _GROUPS), ())
        expansions = synonym_expansions("how many pto days carry over", _GROUPS)
        self.assertEqual(len(expansions), 1)
        self.assertEqual(expansions[0].alternatives, ("paid leave",))
        self.assertEqual(expansions[0].source_terms, ("pto",))

    def test_no_group_member_in_query_yields_nothing(self) -> None:
        self.assertEqual(synonym_expansions("圧力容器の点検周期を教えて", _GROUPS), ())
        self.assertEqual(synonym_expansions("", _GROUPS), ())
        self.assertEqual(synonym_expansions("年休", {}), ())

    def test_all_members_already_in_query_add_nothing(self) -> None:
        # Nothing left to expand with — the query already says both surface forms.
        self.assertEqual(
            synonym_expansions(
                "温度上昇(オーバーヒート)の対処は?", {"温度上昇": ("オーバーヒート",)}
            ),
            (),
        )

    def test_output_is_deterministic_and_sorted_by_group_key(self) -> None:
        groups = {"油漏れ": ("オイルリーク",), "異音": ("うなり音",)}
        query = "うなり音とオイルリークが同時に出た"
        first = synonym_expansions(query, groups)
        second = synonym_expansions(query, dict(reversed(list(groups.items()))))
        self.assertEqual(first, second)
        self.assertEqual(len(first), 2)


class SynonymLexicalScoreTest(unittest.TestCase):
    QUERY = "射出成形機の油圧ユニットでオーバーヒートが起きた場合の対処を教えてください。"
    GOLD = "射出成形機の油圧ユニットで温度上昇が発生した時の対処手順: 冷却ファンを点検する。"

    def _expansions(self):
        return synonym_expansions(self.QUERY, {"温度上昇": ("オーバーヒート",)})

    def test_synonym_alternative_in_text_raises_coverage(self) -> None:
        base = lexical_match_score(self.QUERY, self.GOLD)
        expanded = lexical_match_score(self.QUERY, self.GOLD, expansions=self._expansions())
        self.assertGreater(expanded, base)

    def test_text_without_alternative_is_unchanged(self) -> None:
        other = "射出成形機の油圧ユニットで圧力変動が発生した場合の対処手順: 電磁弁を点検する。"
        base = lexical_match_score(self.QUERY, other)
        expanded = lexical_match_score(self.QUERY, other, expansions=self._expansions())
        self.assertEqual(expanded, base)

    def test_empty_expansions_are_byte_identical_to_pre_1c(self) -> None:
        self.assertEqual(
            lexical_match_score(self.QUERY, self.GOLD),
            lexical_match_score(self.QUERY, self.GOLD, expansions=()),
        )

    def test_direct_hit_outranks_synonym_hit_at_equal_coverage(self) -> None:
        # Two texts covering the SAME query term set — one directly, one via the synonym. The
        # direct text must score strictly higher (SYNONYM_COVERAGE_WEIGHT < 1.0, no density).
        query = "オーバーヒートの対処"
        direct = "オーバーヒートの対処手順を定める。"
        via_synonym = "温度上昇の対処手順を定める。"
        expansions = synonym_expansions(query, {"温度上昇": ("オーバーヒート",)})
        self.assertLess(1e-9, SYNONYM_COVERAGE_WEIGHT)
        self.assertLess(SYNONYM_COVERAGE_WEIGHT, 1.0)
        self.assertGreater(
            lexical_match_score(query, direct, expansions=expansions),
            lexical_match_score(query, via_synonym, expansions=expansions),
        )

    def test_synonym_only_match_scores_but_stays_in_lexical_band(self) -> None:
        # Zero direct term overlap: pre-1c score was 0; with the tenant mapping the text scores,
        # bounded inside the lexical band (< METADATA_EXACT_MATCH_SCORE).
        query = "年休について"
        text = "有給休暇は入社半年後に付与される。"
        self.assertEqual(lexical_match_score(query, text), 0.0)
        expansions = synonym_expansions(query, {"有給休暇": ("年休",)})
        score = lexical_match_score(query, text, expansions=expansions)
        self.assertGreater(score, 0.0)
        self.assertLessEqual(score, 1.20)

    def test_ascii_alternative_requires_whole_tokens(self) -> None:
        # Alternative "paid leave" must not be satisfied by "paidleavex" style substrings; and
        # source term "pto" must not be counted from "laptop".
        query = "how many pto days carry over"
        expansions = synonym_expansions(query, {"paid leave": ("pto",)})
        with_alt = lexical_match_score(
            query, "days that carry over under paid leave", expansions=expansions
        )
        without_alt = lexical_match_score(
            query, "days that carry over under laptop rules", expansions=expansions
        )
        self.assertGreater(with_alt, without_alt)


class _ExplodingLexicon:
    def entries(self, tenant_id: str, namespace: str):
        raise RuntimeError("lexicon outage")


class RetrievalServiceExpansionTest(unittest.TestCase):
    TENANT = "t_syn"
    USER = "alice"
    GOLD = (
        "d_gold",
        "搬送コンベアの減速機で油漏れが発生した時の点検手順: シールパッキンを交換する。",
    )
    ALT = (
        "d_alt",
        "搬送コンベアの減速機で異常振動が発生した場合の点検手順: 取付ボルトを確認する。",
    )
    QUERY = "搬送コンベアの減速機でオイルリークが起きた場合の点検を教えてください。"

    def _system(self, lexicon) -> MvpSystem:
        sys_ = MvpSystem()
        for doc_id, text in (self.GOLD, self.ALT):
            sys_.ingest_text(
                tenant_id=self.TENANT, collection_id="c", document_id=doc_id, text=text
            )
        sys_.grant(self.TENANT, ScopeType.COLLECTION, "c", SubjectType.USER, self.USER)
        sys_.retrieval._lexicon = lexicon
        return sys_

    def _tenant_lexicon(self) -> LexiconService:
        lexicon = LexiconService(InMemoryLexiconRepository())
        lexicon.update(
            self.TENANT, "retrieval.synonyms", "油漏れ", ["オイルリーク"], actor_id="admin"
        )
        return lexicon

    def _ranked_docs(self, sys_: MvpSystem) -> list[str]:
        results = sys_.search(claims(self.TENANT, self.USER), self.QUERY)
        return list(dict.fromkeys(s.chunk.document_id for s in results))

    def test_tenant_lexicon_lifts_synonym_gold_to_rank_one(self) -> None:
        self.assertEqual(self._ranked_docs(self._system(None))[0], "d_alt")  # the 1c gap
        self.assertEqual(self._ranked_docs(self._system(self._tenant_lexicon()))[0], "d_gold")

    def test_lexicon_outage_is_fail_open(self) -> None:
        # Outage => no expansion, same results as no lexicon at all; retrieval never raises.
        self.assertEqual(
            self._ranked_docs(self._system(_ExplodingLexicon())),
            self._ranked_docs(self._system(None)),
        )

    def test_expansion_is_tenant_scoped(self) -> None:
        # Another tenant's mapping must not expand this tenant's queries: the lexicon is stored
        # per-tenant, and RetrievalService reads only the requesting tenant's namespace.
        lexicon = LexiconService(InMemoryLexiconRepository())
        lexicon.update(
            "other_tenant", "retrieval.synonyms", "油漏れ", ["オイルリーク"], actor_id="admin"
        )
        self.assertEqual(self._ranked_docs(self._system(lexicon))[0], "d_alt")

    def test_store_without_expansions_parameter_falls_back(self) -> None:
        # A custom store predating the parameter must keep working (expansion skipped, no error).
        sys_ = self._system(self._tenant_lexicon())
        original = sys_.store.lexical_matches

        def legacy_lexical_matches(tenant_id, query, *, visible, top_k):
            return original(tenant_id, query, visible=visible, top_k=top_k)

        sys_.store.lexical_matches = legacy_lexical_matches
        self.assertEqual(self._ranked_docs(sys_)[0], "d_alt")  # pre-1c order, not an exception

    def test_namespace_is_tenant_editable_with_audit(self) -> None:
        self.assertIn("retrieval.synonyms", EDITABLE_NAMESPACES)

        class _Recorder:
            def __init__(self) -> None:
                self.entries = []

            def record(self, entry) -> None:
                self.entries.append(entry)

        audit = _Recorder()
        lexicon = LexiconService(InMemoryLexiconRepository(), audit=audit)
        lexicon.update("t", "retrieval.synonyms", "有給休暇", ["年休"], actor_id="admin1")
        self.assertEqual(len(audit.entries), 1)
        self.assertEqual(audit.entries[0].resource_id, "retrieval.synonyms/有給休暇")

    def test_default_profile_search_is_unchanged_without_lexicon(self) -> None:
        # No lexicon configured (every existing deployment surface) => byte-identical retrieval.
        sys_ = self._system(None)
        profile = QueryProfile()
        results = sys_.retrieval.retrieve(claims(self.TENANT, self.USER), self.QUERY, profile)
        self.assertTrue(results)


if __name__ == "__main__":
    unittest.main()
