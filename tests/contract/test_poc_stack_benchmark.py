from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class PocStackBenchmarkContractTest(unittest.TestCase):
    def test_two_stage_poc_benchmark_contract_is_pinned(self) -> None:
        harness = (ROOT / "tests/benchmarks/poc_stack_benchmark.py").read_text(encoding="utf-8")
        openapi = (ROOT / "specs/001-rag-platform/contracts/openapi.md").read_text(encoding="utf-8")
        research = (ROOT / "specs/001-rag-platform/research.md").read_text(encoding="utf-8")

        public_tokens = (
            "poc_stack_benchmark",
            "parser_table_structure_accuracy",
            "spreadsheet_cell_citation_accuracy",
            "recall_at_5",
            "exact_code_lookup_success_rate",
            "raw_context_logging_violation_count",
        )
        harness_tokens = (
            "format_results",
            "query_type_metrics",
            "answer_quality_results",
            "security_results",
            "hybrid_metadata_code_vector_rerank",
        )

        for token in public_tokens:
            with self.subTest(token=token):
                self.assertIn(token, harness)
                self.assertIn(token, openapi + research)
        for token in harness_tokens:
            with self.subTest(token=token):
                self.assertIn(token, harness)

        self.assertIn("20 <= self.document_sample_size <= 50", harness)
        self.assertIn("manufacturing", harness)
        self.assertIn("real_estate_property_management", harness)
        self.assertIn("investment_management_mutual_fund", harness)


if __name__ == "__main__":
    unittest.main()
