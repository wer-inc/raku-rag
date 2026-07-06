"""ADR-018 A1 — the async worker's IngestionExecutor rides the structured (Docling) path when enabled."""

from __future__ import annotations

import dataclasses
import unittest

from raku_rag.app import MvpSystem
from raku_rag.core.config import Settings
from raku_rag.domain.models import ScopeType, SubjectType
from raku_rag.workers.ingestion import IngestionExecutor

T = "tenant_worker"


class WorkerStructuredIngestTest(unittest.TestCase):
    def setUp(self) -> None:
        self.system = MvpSystem(
            settings=dataclasses.replace(Settings(), structured_ingest_enabled=True)
        )
        self.system.grant(T, ScopeType.COLLECTION, "c", SubjectType.USER, "alice")
        self.executor = IngestionExecutor(self.system.structured_ingestion)

    def test_executor_uses_structured_service(self) -> None:
        self.assertEqual(type(self.executor.ingestion).__name__, "StructuredIngestionService")

    def test_worker_ingested_mojibake_is_quarantined(self) -> None:
        self.executor.execute_document(
            tenant_id=T,
            collection_id="c",
            source_id="src",
            document_id="wgood",
            raw=b"Pump P-12 maintenance interval ninety days. " * 3,
            content_type="text/plain",
        )
        self.executor.execute_document(
            tenant_id=T,
            collection_id="c",
            source_id="src",
            document_id="wbroken",
            raw=("Pump " + "�" * 40).encode("utf-8"),
            content_type="text/plain",
        )
        docs = {item["document_id"] for item in self.system.list_extraction_reviews(T)}
        self.assertIn("wbroken", docs)
        self.assertNotIn("wgood", docs)


if __name__ == "__main__":
    unittest.main()
