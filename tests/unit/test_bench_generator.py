"""Wave 1a scale-bench generator smoke tests (scripts/bench/).

Keeps the benchmark scripts from rotting: the corpus generator must stay deterministic
(same seed => byte-identical output) and the eval set must stay valid (gold ids exist,
slice invariants hold), and the rank-metric math must stay correct. Stdlib-only, no DB.
"""

from __future__ import annotations

import importlib.util
import json
from collections import Counter
from pathlib import Path
from unittest import TestCase

ROOT = Path(__file__).resolve().parents[2]
BENCH = ROOT / "scripts" / "bench"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, BENCH / f"{name}.py")
    if spec is None or spec.loader is None:
        raise AssertionError(f"could not load scripts/bench/{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestGenerateCorpus(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.gen = _load("generate_corpus")
        cls.corpus = cls.gen.generate(n_docs=500, n_queries=60, seed=7)

    def test_deterministic_for_same_seed(self) -> None:
        again = self.gen.generate(n_docs=500, n_queries=60, seed=7)
        self.assertEqual(
            json.dumps(self.corpus, ensure_ascii=False, sort_keys=True),
            json.dumps(again, ensure_ascii=False, sort_keys=True),
        )

    def test_different_seed_differs(self) -> None:
        other = self.gen.generate(n_docs=500, n_queries=60, seed=8)
        self.assertNotEqual(
            json.dumps(self.corpus, ensure_ascii=False, sort_keys=True),
            json.dumps(other, ensure_ascii=False, sort_keys=True),
        )

    def test_document_ids_unique_and_counts(self) -> None:
        docs = self.corpus["documents"]
        self.assertEqual(len(docs), 500)
        self.assertEqual(len({d["document_id"] for d in docs}), 500)
        kinds = Counter(d["document_kind"] for d in docs)
        self.assertEqual(
            set(kinds), {"work_instruction", "trouble_report", "inspection", "regulation"}
        )

    def test_eval_set_valid(self) -> None:
        docs = self.corpus["documents"]
        queries = self.corpus["queries"]
        self.assertEqual(len(queries), 60)
        doc_ids = {d["document_id"] for d in docs}
        for q in queries:
            gold = set(q["gold_document_ids"])
            self.assertLessEqual(gold, doc_ids, q["query_id"])
            self.assertEqual(q["answerable"], bool(gold), q["query_id"])
            if q["category"] == "unanswerable":
                self.assertEqual(gold, set(), q["query_id"])
            if q["category"] == "multi_doc":
                self.assertGreaterEqual(len(gold), 2, q["query_id"])
        categories = Counter(q["category"] for q in queries)
        self.assertEqual(
            set(categories),
            {"identifier", "paraphrase", "synonym", "multi_doc", "unanswerable"},
        )
        # ~15% unanswerable per the eval-plan slice mix.
        self.assertEqual(categories["unanswerable"], 9)

    def test_paraphrase_and_synonym_golds_have_unique_triples(self) -> None:
        docs = self.corpus["documents"]
        by_id = {d["document_id"]: d for d in docs}
        triples = Counter(
            (d["family_jp"], d["component"], d["symptom"]) for d in docs if d["component"]
        )
        for q in self.corpus["queries"]:
            if q["category"] not in ("paraphrase", "synonym"):
                continue
            (gold_id,) = q["gold_document_ids"]
            d = by_id[gold_id]
            self.assertEqual(
                triples[(d["family_jp"], d["component"], d["symptom"])], 1, q["query_id"]
            )

    def test_synonym_query_forms_never_appear_in_documents(self) -> None:
        all_text = "\n".join(d["title"] + d["content"] for d in self.corpus["documents"])
        for query_form in self.gen.SYMPTOM_SYNONYMS.values():
            self.assertNotIn(query_form, all_text)
        # And the synonym pairs really are zero-bigram-overlap (a shared bigram would let the
        # lexical leg partially match, silently weakening the slice).
        for doc_form, query_form in self.gen.SYMPTOM_SYNONYMS.items():
            doc_bigrams = {doc_form[i : i + 2] for i in range(len(doc_form) - 1)}
            query_bigrams = {query_form[i : i + 2] for i in range(len(query_form) - 1)}
            self.assertEqual(doc_bigrams & query_bigrams, set(), f"{doc_form}->{query_form}")

    def test_unanswerable_identifiers_absent_from_corpus(self) -> None:
        all_text = "\n".join(d["title"] + d["content"] for d in self.corpus["documents"])
        for q in self.corpus["queries"]:
            if q["category"] != "unanswerable":
                continue
            for token in q["question"].replace("。", " ").split():
                if token.startswith(("EQ-", "E-", "SOP-", "INS-", "REG-")):
                    self.assertNotIn(token, all_text, q["query_id"])


class TestRankMetrics(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.bench = _load("run_bench")

    def test_rank_metrics_perfect_and_miss(self) -> None:
        m = self.bench.rank_metrics({"a"}, ["a", "b", "c"])
        self.assertEqual(m["recall@5"], 1.0)
        self.assertEqual(m["mrr@10"], 1.0)
        self.assertEqual(m["ndcg@10"], 1.0)
        m = self.bench.rank_metrics({"z"}, ["a", "b", "c"])
        self.assertEqual(m["recall@5"], 0.0)
        self.assertEqual(m["mrr@10"], 0.0)
        self.assertEqual(m["ndcg@10"], 0.0)

    def test_rank_metrics_partial_multi_doc(self) -> None:
        m = self.bench.rank_metrics({"a", "b"}, ["x", "a", "y", "z", "q", "b"])
        self.assertEqual(m["recall@5"], 0.5)
        self.assertEqual(m["recall@10"], 1.0)
        self.assertEqual(m["mrr@10"], 0.5)
        self.assertGreater(m["ndcg@10"], 0.0)
        self.assertLess(m["ndcg@10"], 1.0)

    def test_percentile_bounds(self) -> None:
        # Nearest-rank definition: within one rank of the exact percentile.
        values = [float(v) for v in range(1, 101)]
        self.assertAlmostEqual(self.bench.percentile(values, 50), 50.0, delta=1.0)
        self.assertAlmostEqual(self.bench.percentile(values, 95), 95.0, delta=1.0)
        self.assertEqual(self.bench.percentile([], 95), 0.0)
