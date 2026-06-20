from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class DocumentationContractTest(unittest.TestCase):
    def test_architecture_provider_and_api_docs_are_published(self) -> None:
        architecture = (ROOT / "docs" / "rag-platform-architecture.md").read_text(encoding="utf-8")
        providers = (ROOT / "docs" / "provider-replacement-guide.md").read_text(encoding="utf-8")
        examples = (ROOT / "docs" / "api-examples.md").read_text(encoding="utf-8")

        self.assertIn("tenant + tombstone + ACL", architecture)
        self.assertIn("Visual RAG", architecture)
        for name in (
            "Connector",
            "Parser",
            "Chunker",
            "EmbeddingProvider",
            "VectorStore",
            "Reranker",
            "LLMProvider",
            "TaskQueue",
            "OcrEngine",
            "LayoutExtractor",
            "CaptioningProvider",
            "VisualEmbeddingProvider",
            "VLMProvider",
        ):
            with self.subTest(provider=name):
                self.assertIn(name, providers)
        self.assertIn("/v1/search", examples)
        self.assertIn("/v1/answer", examples)
        self.assertIn("/v1/assets", examples)
        self.assertIn("/v1/evaluations", examples)

    def test_industry_uat_usecases_are_published(self) -> None:
        uat = (ROOT / "docs" / "uat" / "industry-usecases.md").read_text(encoding="utf-8")
        fixtures = (ROOT / "tests" / "fixtures" / "uat" / "README.md").read_text(encoding="utf-8")

        for spec in (
            "001-rag-platform",
            "002-manufacturing-field-knowledge-rag",
            "003-real-estate-property-management-rag",
            "006-investment-management-mutual-fund-rag",
            "010-industry-solution-framework",
        ):
            with self.subTest(spec=spec):
                self.assertIn(spec, uat)

        for case_id in (
            "X-01",
            "X-02",
            "X-03",
            "X-04",
            "MFG-01",
            "MFG-02",
            "MFG-03",
            "MFG-04",
            "MFG-05",
            "MFG-06",
            "MFG-07",
            "RE-01",
            "RE-02",
            "RE-03",
            "RE-04",
            "RE-05",
            "RE-06",
            "RE-07",
            "RE-08",
            "INV-01",
            "INV-02",
            "INV-03",
            "INV-04",
            "INV-05",
            "INV-06",
            "INV-07",
            "INV-08",
        ):
            with self.subTest(case_id=case_id):
                self.assertIn(case_id, uat)

        for required in (
            "Expected citation",
            "Expected risk gate",
            "Expected DraftArtifact",
            "Expected audit event",
            "Expected dashboard/KPI",
            "Hard fail",
            "Phase Execution Order",
        ):
            with self.subTest(required=required):
                self.assertIn(required, uat)

        for fixture_section in (
            "Shared Fixtures",
            "Manufacturing Fixtures",
            "Real Estate Fixtures",
            "Investment Fixtures",
            "Phase Execution Order",
        ):
            with self.subTest(fixture_section=fixture_section):
                self.assertIn(fixture_section, fixtures)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
