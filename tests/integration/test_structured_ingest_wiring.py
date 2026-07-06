"""ADR-018 A1 — the structured_ingest_enabled flag routes the app's ingest entrypoint (default OFF).

Proves MvpSystem.ingest_text uses the legacy IngestionService by default and the Docling-first
StructuredIngestionService when the flag is on, with content still retrievable either way.
"""

from __future__ import annotations

import dataclasses
import unittest

from raku_rag.app import MvpSystem
from raku_rag.core.config import Settings
from raku_rag.domain.models import QueryProfile, ScopeType, SubjectType
from raku_rag.services.ingestion import IngestionService
from raku_rag.services.structured_ingestion import StructuredIngestionService
from tests.helpers import claims

T = "tenant_wire"


def _system(*, structured: bool) -> MvpSystem:
    settings = dataclasses.replace(Settings(), structured_ingest_enabled=structured)
    sys = MvpSystem(settings=settings)
    sys.grant(T, ScopeType.COLLECTION, "c", SubjectType.USER, "alice")
    return sys


class StructuredIngestWiringTest(unittest.TestCase):
    def test_flag_off_uses_legacy_service(self) -> None:
        sys = _system(structured=False)
        self.assertIsNone(sys.structured_ingestion)
        self.assertIs(sys._ingest, sys.ingestion)
        self.assertIsInstance(sys._ingest, IngestionService)

    def test_flag_on_routes_ingest_through_structured_service(self) -> None:
        sys = _system(structured=True)
        self.assertIsInstance(sys.structured_ingestion, StructuredIngestionService)
        self.assertIs(sys._ingest, sys.structured_ingestion)

        job = sys.ingest_text(
            tenant_id=T,
            collection_id="c",
            document_id="d1",
            text="Pump P-30 maintenance interval is ninety days.",
        )
        self.assertEqual(job.status, "succeeded", job.failure_reason)

        # chunk carries the structured contract metadata (proof it went through the structured path)
        chunk = next(c for c, _v in sys.store.iter_items() if c.document_id == "d1")
        self.assertEqual(chunk.metadata.get("parser_contract_version"), "v1")
        self.assertIn("parsed_chunk_kind", chunk.metadata)

        # and it is retrievable through the normal retrieval service
        result = sys.retrieval.retrieve(
            claims(T, "alice"),
            "Pump P-30 maintenance interval",
            QueryProfile(top_k=10, rerank_enabled=False),
        )
        self.assertIn("d1", {item.chunk.document_id for item in result})


if __name__ == "__main__":
    unittest.main()
