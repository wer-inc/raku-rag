from __future__ import annotations

import unittest

from raku_rag.dagster.checks.quality import (
    check_acl_leakage,
    check_baseline_regression,
    check_chunk_count,
    check_deleted_documents_not_searchable,
    check_embedding_coverage,
    check_parser_output_schema,
    check_spreadsheet_citation_cell_ranges,
    check_tenant_isolation,
)
from raku_rag.domain.models import Chunk, Modality


class TestQualityChecks(unittest.TestCase):
    def test_embedding_chunk_parser_and_cell_range_checks(self) -> None:
        chunk = Chunk(
            tenant_id="t",
            collection_id="c",
            document_id="d1",
            chunk_id="d1:0",
            text="hello",
            modality=Modality.TEXT,
            embedding_model_version="embed-v1",
        )

        self.assertTrue(check_embedding_coverage([chunk]).passed)
        self.assertTrue(check_chunk_count("d1", 1).passed)
        self.assertTrue(check_parser_output_schema(["normalized text"]).passed)
        self.assertTrue(check_spreadsheet_citation_cell_ranges([]).passed)
        self.assertFalse(check_parser_output_schema([""]).passed)

    def test_security_and_regression_checks(self) -> None:
        self.assertTrue(check_deleted_documents_not_searchable(["d1"], ["d2"]).passed)
        self.assertFalse(check_deleted_documents_not_searchable(["d1"], ["d1"]).passed)
        self.assertTrue(check_acl_leakage(0).passed)
        self.assertFalse(check_acl_leakage(1).passed)
        self.assertTrue(check_tenant_isolation(0).passed)
        self.assertFalse(check_tenant_isolation(1).passed)
        self.assertTrue(
            check_baseline_regression(
                {"recall_at_k": 1.0, "citation_accuracy": 1.0},
                {"recall_at_k": 1.0, "citation_accuracy": 1.0},
            ).passed
        )
        self.assertFalse(
            check_baseline_regression(
                {"recall_at_k": 0.8, "citation_accuracy": 1.0},
                {"recall_at_k": 1.0, "citation_accuracy": 1.0},
            ).passed
        )


if __name__ == "__main__":
    unittest.main()
