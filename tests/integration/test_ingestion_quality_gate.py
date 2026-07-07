"""ADR 018 ingestion quality gate across retrieval and answer evidence."""

from __future__ import annotations

from dataclasses import replace
import unittest

from raku_rag.core.errors import AnswerStatus
from raku_rag.domain.models import QueryProfile, ScopeType, ScoredChunk, SubjectType
from raku_rag.services.answer import AnswerService
from raku_rag.services.ingestion_quality import (
    EXTRACTION_QUALITY_SCHEMA_VERSION,
    EXTRACTION_QUALITY_SCHEMA_VERSION_KEY,
    EXTRACTION_QUALITY_STATUS_KEY,
    QUALITY_STATUS_ACCEPTED,
    QUALITY_STATUS_REVIEW_REQUIRED,
    review_required_quality_metadata,
)
from tests.helpers import claims, fresh

T = "tenant_a"


class _FakeRetrieval:
    def __init__(self, evidence: tuple[ScoredChunk, ...]) -> None:
        self._evidence = evidence

    def retrieve(self, principal, query, profile, *, correlation_id: str = ""):
        return list(self._evidence)


class IngestionQualityGateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.sys = fresh()
        self.sys.grant(T, ScopeType.COLLECTION, "c", SubjectType.USER, "alice")
        self.alice = claims(T, "alice")

    def _stored_chunk(self, document_id: str):
        iter_items = getattr(self.sys.store, "iter_items", None)
        if not callable(iter_items):
            self.skipTest("store does not expose in-memory iter_items")
        for chunk, vector in iter_items():
            if chunk.document_id == document_id:
                return chunk, vector
        self.fail(f"missing stored chunk for {document_id}")

    def test_text_ingestion_stamps_default_quality_metadata(self) -> None:
        job = self.sys.ingest_text(
            tenant_id=T,
            collection_id="c",
            document_id="quality-doc",
            text="Pump P-12 maintenance interval is ninety days.",
        )
        self.assertEqual(job.status, "succeeded", job.failure_reason)

        doc = self.sys.registry.get(T, "quality-doc")
        self.assertIsNotNone(doc)
        self.assertEqual(
            doc.metadata[EXTRACTION_QUALITY_SCHEMA_VERSION_KEY],
            EXTRACTION_QUALITY_SCHEMA_VERSION,
        )
        self.assertEqual(doc.metadata[EXTRACTION_QUALITY_STATUS_KEY], QUALITY_STATUS_ACCEPTED)

        chunk, _vector = self._stored_chunk("quality-doc")
        self.assertEqual(chunk.metadata[EXTRACTION_QUALITY_STATUS_KEY], QUALITY_STATUS_ACCEPTED)

    def test_ingestion_quarantines_review_required_chunks_before_retrieval(self) -> None:
        # A genuinely-broken (mojibake) extraction is classified review_required at INGEST, so this
        # exercises the real ingest -> classify -> physical quarantine path and stays backend-agnostic
        # (no store surgery that a Postgres backend can't round-trip).
        self.sys.ingest_text(
            tenant_id=T,
            collection_id="c",
            document_id="needs-review",
            text="Pump P-12 maintenance interval " + "�" * 40,
            chunking_metadata={"asset_tag": "P-12"},
        )
        self.sys.ingest_text(
            tenant_id=T,
            collection_id="c",
            document_id="accepted",
            text="Pump P-12 maintenance interval is ninety days.",
            chunking_metadata={"asset_tag": "P-12"},
        )
        review_doc = self.sys.registry.get(T, "needs-review")
        self.assertEqual(
            review_doc.metadata[EXTRACTION_QUALITY_STATUS_KEY], QUALITY_STATUS_REVIEW_REQUIRED
        )
        self.assertFalse(
            any(
                chunk.document_id == "needs-review"
                for chunk, _vector in self.sys.store.iter_items()
            )
        )
        self.assertTrue(
            any(
                chunk.document_id == "needs-review"
                for chunk, _vector in self.sys.store.iter_quarantine_items()
            )
        )

        profile = QueryProfile(top_k=10, rerank_enabled=False)
        result = self.sys.retrieval.retrieve(
            self.alice, "Pump P-12 maintenance interval", profile, correlation_id="quality-cid"
        )

        self.assertTrue(result)
        self.assertNotIn("needs-review", {item.chunk.document_id for item in result})
        self.assertIn("accepted", {item.chunk.document_id for item in result})
        queue = self.sys.list_extraction_reviews(T)
        self.assertIn("needs-review", {item["document_id"] for item in queue})

    def test_answer_revalidation_rejects_quality_ineligible_fake_retrieval(self) -> None:
        self.sys.ingest_text(
            tenant_id=T,
            collection_id="c",
            document_id="fake-review",
            text="Pump P-12 maintenance interval is thirty days.",
        )
        chunk, _vector = self._stored_chunk("fake-review")
        review_chunk = replace(
            chunk,
            metadata={
                **chunk.metadata,
                **review_required_quality_metadata(reasons=("test_fake_retrieval",)),
            },
        )
        answer = AnswerService(
            _FakeRetrieval((ScoredChunk(review_chunk, 1.0),)),
            self.sys.llm,
            self.sys.gate,
            self.sys.cost,
            self.sys.registry.get,
            self.sys.metrics,
            self.sys.tracer,
            self.sys.audit,
            self.sys.vlm,
            settings=self.sys.settings,
        ).answer(
            self.alice,
            "What is the Pump P-12 maintenance interval?",
            QueryProfile(rerank_enabled=False),
        )

        self.assertEqual(answer.status, AnswerStatus.INSUFFICIENT_EVIDENCE.value)
        self.assertEqual(answer.used_chunks, ())
        self.assertEqual(
            review_chunk.metadata[EXTRACTION_QUALITY_STATUS_KEY], QUALITY_STATUS_REVIEW_REQUIRED
        )


if __name__ == "__main__":
    unittest.main()
