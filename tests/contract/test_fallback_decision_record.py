from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class FallbackDecisionRecordContractTest(unittest.TestCase):
    def test_research_records_benchmark_fallback_criteria(self) -> None:
        research = (ROOT / "specs/001-rag-platform/research.md").read_text(encoding="utf-8")

        for token in (
            "R16b. Benchmark fallback decision record",
            "OpenSearch hybrid search",
            "Qdrant vector store",
            "Titan embeddings",
            "Parser provider fallback",
            "OSS parser fallback",
            "ACL leakage",
            "raw-context logging",
        ):
            with self.subTest(token=token):
                self.assertIn(token, research)

        self.assertIn("raw document bytes", research)
        self.assertIn("benchmark runs", research)


if __name__ == "__main__":
    unittest.main()
