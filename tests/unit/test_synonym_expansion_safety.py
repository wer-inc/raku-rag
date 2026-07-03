"""Wave 1c safety invariants — synonym expansion is a LEXICAL-LEG-ONLY retrieval widening.

Mirrors the #78 (intent_query threading) test style: kept in its OWN file so protected hard-gate
files stay unmodified, and every invariant is asserted on observable behavior:

1. Expansion never reaches the embedding leg, the metadata-exact leg, or the query plan — those
   see the RAW query byte-identically with and without a tenant lexicon.
2. Expansion never reaches the no-answer gate's judgment: ``salient_coverage_check`` (and the
   legacy ``question_coverage_check``) receive the ORIGINAL query. The pinned contract (#80):
   salient coverage judges the ORIGINAL query, and a synonym-expanded lexical hit still has to
   pass it — a question responsive ONLY through a synonym mapping is retrieved but REFUSED
   (fail-safe: expansion can widen recall, never widen what counts as responsive).
3. Expansion never reaches the manufacturing high-risk classification (intent_query channel):
   a tenant ``retrieval.synonyms`` entry can neither launder a high-risk query into a benign one
   nor conjure a high-risk classification for a benign query (#78 invariant).
"""

from __future__ import annotations

import unittest

from raku_rag.app import MvpSystem
from raku_rag.domain.models import ScopeType, SubjectType
from raku_rag.persistence.lexicon import InMemoryLexiconRepository
from raku_rag.services.groundedness import GroundednessGate
from raku_rag.services.lexicon import LexiconService
from tests.helpers import claims

T = "t_syn_safety"
USER = "op"


def _lexicon(tenant: str, entries: dict[str, list[str]]) -> LexiconService:
    lexicon = LexiconService(InMemoryLexiconRepository())
    for key, values in entries.items():
        lexicon.update(tenant, "retrieval.synonyms", key, values, actor_id="admin")
    return lexicon


class _RecordingEmbedder:
    """Wraps the real embedder, recording every embedded text."""

    def __init__(self, inner) -> None:
        self._inner = inner
        self.embedded: list[str] = []

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def embed(self, texts):
        self.embedded.extend(texts)
        return self._inner.embed(texts)


class _RecordingStore:
    """Wraps the real store, recording the query text each hybrid leg receives."""

    def __init__(self, inner) -> None:
        self._inner = inner
        self.metadata_queries: list[str] = []
        self.lexical_queries: list[str] = []
        self.lexical_expansions: list[tuple] = []

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def metadata_exact_matches(self, tenant_id, query, *, visible, top_k):
        self.metadata_queries.append(query)
        return self._inner.metadata_exact_matches(tenant_id, query, visible=visible, top_k=top_k)

    def lexical_matches(self, tenant_id, query, *, visible, top_k, expansions=()):
        self.lexical_queries.append(query)
        self.lexical_expansions.append(tuple(expansions))
        return self._inner.lexical_matches(
            tenant_id, query, visible=visible, top_k=top_k, expansions=expansions
        )


class _RecordingGate(GroundednessGate):
    """Real gate, recording the query each coverage check judges."""

    def __init__(self) -> None:
        super().__init__()
        self.salient_queries: list[str] = []
        self.legacy_queries: list[str] = []

    def salient_coverage_check(self, query, evidence):
        self.salient_queries.append(query)
        return super().salient_coverage_check(query, evidence)

    def question_coverage_check(self, query, evidence, threshold):
        self.legacy_queries.append(query)
        return super().question_coverage_check(query, evidence, threshold)


def _base_system(lexicon) -> MvpSystem:
    sys_ = MvpSystem()
    sys_.ingest_text(
        tenant_id=T,
        collection_id="c",
        document_id="d_leave",
        text="有給休暇は入社半年後に10日付与され、翌年度まで繰り越しできる。",
    )
    sys_.grant(T, ScopeType.COLLECTION, "c", SubjectType.USER, USER)
    sys_.retrieval._lexicon = lexicon
    return sys_


class ExpansionNeverLeavesTheLexicalLegTest(unittest.TestCase):
    QUERY = "年休の繰越について教えてください。"

    def test_embedding_metadata_legs_and_plan_see_the_raw_query(self) -> None:
        sys_ = _base_system(_lexicon(T, {"有給休暇": ["年休"]}))
        embedder = _RecordingEmbedder(sys_.embedder)
        store = _RecordingStore(sys_.store)
        sys_.retrieval._embedder = embedder
        sys_.retrieval._store = store
        sys_.search(claims(T, USER), self.QUERY)
        # Embedding leg: exactly the raw query (no synonym text appended or substituted).
        self.assertEqual(embedder.embedded, [self.QUERY])
        # Metadata-exact leg: raw query.
        self.assertEqual(store.metadata_queries, [self.QUERY])
        # Lexical leg: raw query TEXT plus a separate, structured expansions argument.
        self.assertEqual(store.lexical_queries, [self.QUERY])
        self.assertEqual(len(store.lexical_expansions), 1)
        self.assertTrue(store.lexical_expansions[0])
        self.assertIn("有給休暇", store.lexical_expansions[0][0].alternatives)

    def test_coverage_gate_judges_the_original_query(self) -> None:
        # A query that produces an answer, so the coverage checks actually run — then assert the
        # judged text is the ORIGINAL query, with no synonym text appended or substituted.
        query = "年休は入社後いつ付与され、繰り越しできますか。"
        sys_ = _base_system(_lexicon(T, {"有給休暇": ["年休"]}))
        gate = _RecordingGate()
        sys_.answer_service._gate = gate
        answer = sys_.answer(claims(T, USER), query)
        self.assertEqual(answer.status, "ok")
        self.assertTrue(gate.salient_queries)
        for judged in gate.salient_queries + gate.legacy_queries:
            self.assertEqual(judged, query)


class CoverageGateStillBindsExpandedHitsTest(unittest.TestCase):
    def test_synonym_only_responsive_evidence_is_retrieved_but_refused(self) -> None:
        # THE contract (#80): the question's only salient content word (年休) is satisfiable ONLY
        # through the tenant synonym. Expansion makes retrieval find the document — and the
        # salient-coverage gate, judging the ORIGINAL query, still refuses. Expansion widens
        # recall; it never widens what counts as responsive.
        lexicon = _lexicon(T, {"有給休暇": ["年休"]})
        sys_ = _base_system(lexicon)
        principal = claims(T, USER)
        query = "年休の繰越を教えて"

        retrieved = sys_.search(principal, query)
        self.assertIn("d_leave", {s.chunk.document_id for s in retrieved})  # expansion worked

        answer = sys_.answer(principal, query)
        self.assertEqual(answer.status, "insufficient_evidence")  # the gate still binds

    def test_mixed_query_with_direct_salient_coverage_answers(self) -> None:
        # Enough of the question's salient terms (繰越, 入社, 付与...) are covered DIRECTLY by the
        # evidence — the synonym only disambiguates retrieval — so the same gate passes: no
        # over-refusal introduced by keeping the gate expansion-blind.
        sys_ = _base_system(_lexicon(T, {"有給休暇": ["年休"]}))
        answer = sys_.answer(claims(T, USER), "年休は入社後いつ付与され、繰り越しできますか。")
        self.assertEqual(answer.status, "ok")
        self.assertIn("d_leave", {c.document_id for c in answer.citations})

    def test_absent_content_still_refuses_with_lexicon_configured(self) -> None:
        # An unanswerable question (about content that does not exist) must keep refusing when a
        # tenant lexicon exists — no expansion-induced unanswerable_answer regression.
        sys_ = _base_system(_lexicon(T, {"有給休暇": ["年休"]}))
        answer = sys_.answer(claims(T, USER), "社宅の入居条件と家賃補助の上限を教えてください。")
        self.assertEqual(answer.status, "insufficient_evidence")


class ExpansionNeverReachesHighRiskClassificationTest(unittest.TestCase):
    """#78 invariant at the manufacturing boundary: classification binds to the raw intent."""

    def _mfg_system(self, lexicon_entries: dict[str, list[str]] | None):
        from raku_rag.manufacturing.app import ManufacturingSystem
        from tests.manufacturing.helpers import mfg_meta

        sys_ = ManufacturingSystem()
        sys_.ingest_manufacturing(
            tenant_id=T,
            collection_id="c",
            document_id="d_generic",
            text="休憩室の利用時間は平日の正午から午後一時までとする。",
            metadata=mfg_meta(tenant_id=T, document_id="d_generic"),
        )
        sys_.grant(T, ScopeType.COLLECTION, "c", SubjectType.USER, USER)
        if lexicon_entries is not None:
            sys_._mvp.retrieval._lexicon = _lexicon(T, lexicon_entries)
        return sys_

    def test_benign_query_with_danger_word_synonym_stays_benign(self) -> None:
        # A tenant maps a HIGH-RISK keyword (感電) to a benign word the query uses. The retrieval
        # leg may expand, but the high-risk classification/query signal must keep judging the raw
        # query text. (English benign query: a terse Japanese one would trip the classifier's
        # UNRELATED "too short to rule danger out" fail-safe — see
        # tests/manufacturing/test_high_risk_query_signal.py.)
        entries = {"感電": ["cafeteria"]}
        with_lexicon = self._mfg_system(entries)
        without_lexicon = self._mfg_system(None)
        query = "where is the employee cafeteria located inside building seven"
        self.assertFalse(with_lexicon.is_high_risk_query_signal(query))
        ans_with = with_lexicon.answer(claims(T, USER), query)
        ans_without = without_lexicon.answer(claims(T, USER), query)
        self.assertEqual(ans_with.high_risk, ans_without.high_risk)
        self.assertEqual(ans_with.high_risk_reason_codes, ans_without.high_risk_reason_codes)
        self.assertFalse(ans_with.high_risk)

    def test_high_risk_query_cannot_be_laundered_by_synonyms(self) -> None:
        # The reverse direction: mapping the danger word to benign synonyms must not weaken the
        # classification — the high-risk query stays high-risk (and blocked without an approved
        # responsive citation), lexicon or not.
        entries = {"休憩室": ["感電", "活線"]}
        with_lexicon = self._mfg_system(entries)
        query = "活線作業で感電を防ぐ手順を教えてください。"
        self.assertTrue(with_lexicon.is_high_risk_query_signal(query))
        answer = with_lexicon.answer(claims(T, USER), query)
        self.assertTrue(answer.high_risk)
        self.assertNotEqual(answer.status, "ok")


if __name__ == "__main__":
    unittest.main()
