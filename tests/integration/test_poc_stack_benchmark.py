from __future__ import annotations

import unittest

from tests.benchmarks.poc_stack_benchmark import (
    DEFAULT_EMBEDDING_MODELS,
    DEFAULT_INDUSTRY_IDS,
    DEFAULT_PARSER_PROVIDERS,
    DEFAULT_RETRIEVAL_PROFILES,
    HARD_GATES,
    SECURITY_PROBES,
    SOURCE_FORMATS,
    STAGE1_METRICS,
    STAGE2_METRICS,
    PocBenchmarkRequest,
    PocStackBenchmarkHarness,
)


class PocStackBenchmarkHarnessTest(unittest.TestCase):
    def test_plan_builds_twenty_japanese_documents_per_industry_and_two_stage_matrix(self) -> None:
        harness = PocStackBenchmarkHarness()
        request = PocBenchmarkRequest(document_sample_size=20)

        plan = harness.plan(request)
        payload = plan.to_dict()

        self.assertEqual(plan.benchmark_type, "poc_stack_benchmark")
        self.assertEqual(payload["document_count"], 20 * len(DEFAULT_INDUSTRY_IDS))
        self.assertEqual(payload["eval_item_count"], 20 * len(DEFAULT_INDUSTRY_IDS))
        self.assertEqual(
            len(plan.stage1_matrix), len(DEFAULT_INDUSTRY_IDS) * len(DEFAULT_PARSER_PROVIDERS)
        )
        self.assertEqual(
            len(plan.stage2_matrix),
            len(DEFAULT_INDUSTRY_IDS)
            * len(DEFAULT_EMBEDDING_MODELS)
            * len(DEFAULT_RETRIEVAL_PROFILES),
        )
        self.assertEqual(tuple(payload["hard_gates"]), HARD_GATES)
        for corpus in plan.corpora:
            with self.subTest(industry=corpus.profile.industry_id):
                self.assertEqual(len(corpus.documents), 20)
                self.assertEqual(
                    {doc.source_format for doc in corpus.documents}, set(SOURCE_FORMATS)
                )
                self.assertTrue(all("識別子" in doc.text for doc in corpus.documents))
                self.assertTrue(all(doc.metadata["language"] == "ja" for doc in corpus.documents))
                self.assertTrue(all(query.expected_document_id for query in corpus.queries))

        self.assertTrue(set(STAGE1_METRICS).issubset(set(payload["metrics"])))
        self.assertTrue(set(STAGE2_METRICS).issubset(set(payload["metrics"])))

    def test_sample_size_supports_fifty_and_rejects_out_of_range(self) -> None:
        harness = PocStackBenchmarkHarness()

        large = harness.plan(PocBenchmarkRequest(document_sample_size=50))

        self.assertEqual(
            sum(len(corpus.documents) for corpus in large.corpora), 50 * len(DEFAULT_INDUSTRY_IDS)
        )
        with self.assertRaises(ValueError):
            harness.plan(PocBenchmarkRequest(document_sample_size=19))
        with self.assertRaises(ValueError):
            harness.plan(PocBenchmarkRequest(document_sample_size=51))

    def test_run_offline_accepts_stage_evaluator_overrides_and_returns_api_shape(self) -> None:
        harness = PocStackBenchmarkHarness()
        request = PocBenchmarkRequest(
            industry_ids=("manufacturing",),
            document_sample_size=20,
            parser_providers=("aws_textract",),
            embedding_models=("cohere-embed-multilingual-v3",),
            retrieval_profiles=("metadata_code_vector_rerank",),
        )

        run = harness.run_offline(
            request,
            parser_evaluator=lambda _doc, _provider: {metric: 1.0 for metric in STAGE1_METRICS},
            retrieval_evaluator=lambda _eval_set, _industry, _embedding, _profile: {
                metric: 1.0 for metric in STAGE2_METRICS
            },
        )
        payload = run.to_dict()

        self.assertEqual(payload["benchmark_type"], "poc_stack_benchmark")
        self.assertEqual(payload["status"], "succeeded")
        self.assertEqual(len(payload["parser_results"]), 1)
        self.assertEqual(len(payload["retrieval_results"]), 1)
        self.assertTrue(all(value == 0 for value in payload["hard_gates"].values()))
        self.assertEqual(payload["metrics"]["recall_at_5"], 1.0)
        self.assertEqual(payload["metrics"]["parser_table_structure_accuracy"], 1.0)
        self.assertEqual(payload["recommendation"]["parser_provider"], "aws_textract")
        self.assertEqual(
            payload["recommendation"]["retrieval_profile"], "metadata_code_vector_rerank"
        )
        self.assertTrue(payload["answer_quality_results"])
        self.assertTrue(payload["security_results"])
        self.assertTrue(payload["fallback_paths"])

    def test_parser_provider_benchmark_reports_provider_and_source_format_breakdown(self) -> None:
        harness = PocStackBenchmarkHarness()
        request = PocBenchmarkRequest(industry_ids=("manufacturing",), document_sample_size=20)

        run = harness.run_offline(request)
        by_provider = {row["parser_provider"]: row for row in run.parser_results}

        self.assertEqual(set(by_provider), set(DEFAULT_PARSER_PROVIDERS))
        for provider, row in by_provider.items():
            with self.subTest(provider=provider):
                self.assertEqual(
                    {item["source_format"] for item in row["format_results"]}, set(SOURCE_FORMATS)
                )
                self.assertIn("parser_table_structure_accuracy", row["metrics"])
                self.assertIn("spreadsheet_cell_citation_accuracy", row["metrics"])
        self.assertGreater(
            by_provider["azure_document_intelligence"]["metrics"][
                "parser_table_structure_accuracy"
            ],
            by_provider["tesseract"]["metrics"]["parser_table_structure_accuracy"],
        )
        self.assertGreater(
            by_provider["google_document_ai"]["metrics"]["spreadsheet_cell_citation_accuracy"],
            by_provider["tesseract"]["metrics"]["spreadsheet_cell_citation_accuracy"],
        )

    def test_embedding_retrieval_benchmark_compares_models_profiles_and_hybrid_search(self) -> None:
        harness = PocStackBenchmarkHarness()
        request = PocBenchmarkRequest(industry_ids=("manufacturing",), document_sample_size=20)

        run = harness.run_offline(request)
        by_combo = {
            (row["embedding_model"], row["retrieval_profile"]): row for row in run.retrieval_results
        }
        cohere_hybrid = by_combo[
            ("cohere-embed-multilingual-v3", "hybrid_metadata_code_vector_rerank")
        ]
        titan_vector = by_combo[("amazon-titan-embed-text-v2", "vector_rerank")]

        self.assertEqual(set(DEFAULT_RETRIEVAL_PROFILES), {key[1] for key in by_combo})
        self.assertEqual(set(DEFAULT_EMBEDDING_MODELS), {key[0] for key in by_combo})
        self.assertGreater(
            cohere_hybrid["metrics"]["recall_at_5"], titan_vector["metrics"]["recall_at_5"]
        )
        self.assertGreater(
            cohere_hybrid["metrics"]["exact_code_lookup_success_rate"],
            titan_vector["metrics"]["exact_code_lookup_success_rate"],
        )
        query_types = {item["query_type"] for item in cohere_hybrid["query_type_metrics"]}
        self.assertIn("exact_code_lookup", query_types)
        self.assertIn("spreadsheet_cell_citation", query_types)
        self.assertIn("high_risk_gate", query_types)

    def test_answer_quality_and_security_hard_gate_results_are_explicit(self) -> None:
        harness = PocStackBenchmarkHarness()
        request = PocBenchmarkRequest(
            industry_ids=("manufacturing",),
            document_sample_size=20,
            parser_providers=("aws_textract",),
            embedding_models=("cohere-embed-multilingual-v3",),
            retrieval_profiles=("metadata_code_vector_rerank",),
        )

        passed = harness.run_offline(request)
        blocked = harness.run_offline(
            request,
            security_evaluator=lambda _plan: {
                "acl_leakage_count": 1,
                "raw_context_logging_violation_count": 2,
            },
        )

        self.assertEqual(passed.status, "succeeded")
        self.assertEqual(blocked.status, "blocked")
        self.assertEqual(set(blocked.hard_gates), set(HARD_GATES))
        self.assertEqual(len(blocked.security_results), len(SECURITY_PROBES))
        self.assertTrue(any(not row["passed"] for row in blocked.security_results))
        quality = blocked.answer_quality_results[0]
        self.assertIn("citation_accuracy", quality["metrics"])
        self.assertIn("groundedness", quality["metrics"])
        self.assertIn("insufficient_evidence_correct_rejection_rate", quality["metrics"])
        self.assertIn("high_risk_gate_compliance", quality["metrics"])


if __name__ == "__main__":
    unittest.main()
