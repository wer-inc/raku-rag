"""Production-track ingestion worker contracts (P1-T31/T34/T42, T100).

These tests keep Tier A Docker-free while pinning the behavior the LocalStack/SQS adapter must keep:
message contract, idempotent redelivery, status projection, and DLQ handoff.
"""

from __future__ import annotations

import unittest

from raku_rag.app import MvpSystem
from raku_rag.domain.models import JobStatus
from raku_rag.providers.connectors import MemoryConnector
from raku_rag.providers.mock.visual import FakeAsyncDocumentAnalyzer, page_with_text
from raku_rag.providers.task_queue import InMemoryMessageQueue
from raku_rag.workers.ingestion import (
    IngestionExecutor,
    IngestionJobMessage,
    IngestionRunStore,
    IngestionWorker,
)


class TestIngestionWorkerQueue(unittest.TestCase):
    def setUp(self) -> None:
        self.sys = MvpSystem()
        self.connector = MemoryConnector()
        self.queue = InMemoryMessageQueue(max_receive_count=2)
        self.runs = IngestionRunStore()
        self.worker = IngestionWorker(
            queue=self.queue,
            connector=self.connector,
            ingestion=self.sys.ingestion,
            runs=self.runs,
        )

    def _message(
        self,
        *,
        key: str = "idem-1",
        ref: str = "mem://doc1",
        content_type: str = "text/plain",
    ) -> IngestionJobMessage:
        return IngestionJobMessage(
            idempotency_key=key,
            tenant_id="tenant_a",
            collection_id="manuals",
            source_id="upload",
            document_id="doc1",
            document_ref=ref,
            content_type=content_type,
        )

    def test_enqueue_creates_queued_run_and_worker_indexes_document(self) -> None:
        self.connector.put("mem://doc1", b"Pump P-12 maintenance interval is ninety days.")
        run = self.worker.enqueue(self._message())

        self.assertEqual(run.status, JobStatus.QUEUED.value)
        self.assertEqual(self.queue.available_count, 1)

        self.worker.drain()

        run = self.runs.get(run.ingestion_run_id)
        state = self.runs.processing_state("tenant_a", "doc1")
        doc = self.sys.registry.get("tenant_a", "doc1")
        self.assertIsNotNone(run)
        self.assertIsNotNone(state)
        self.assertIsNotNone(doc)
        self.assertEqual(run.status, JobStatus.SUCCEEDED.value)
        self.assertEqual(state.status, JobStatus.SUCCEEDED.value)
        self.assertGreater(run.chunk_count, 0)
        self.assertTrue(state.content_checksum)
        self.assertEqual(state.parser_version, "text-parser-v1")
        self.assertEqual(state.chunking_config_version, "sentence-chunker-v1")
        self.assertEqual(state.embedding_model_version, self.sys.embedder.model_version)
        self.assertEqual(self.queue.available_count, 0)
        self.assertEqual(self.queue.dlq_count, 0)

    def test_redelivered_same_idempotency_key_does_not_reindex(self) -> None:
        self.connector.put("mem://doc1", b"Alarm A-17 reset requires lockout confirmation.")
        msg = self._message(key="same-key")
        self.queue.enqueue_message(msg.to_dict())
        self.queue.enqueue_message(msg.to_dict())

        self.worker.drain()

        run = self.runs.get_by_idempotency_key("tenant_a", "same-key")
        doc = self.sys.registry.get("tenant_a", "doc1")
        self.assertIsNotNone(run)
        self.assertIsNotNone(doc)
        self.assertEqual(run.status, JobStatus.SUCCEEDED.value)
        self.assertEqual(doc.version, 1)
        self.assertEqual(self.worker.stats.processed, 1)
        self.assertEqual(self.worker.stats.skipped_duplicates, 1)

    def test_failed_fetch_retries_then_moves_to_dlq_and_projects_state(self) -> None:
        run = self.worker.enqueue(self._message(key="missing", ref="mem://missing"))

        self.worker.drain(max_messages=4)

        run = self.runs.get(run.ingestion_run_id)
        state = self.runs.processing_state("tenant_a", "doc1")
        self.assertIsNotNone(run)
        self.assertIsNotNone(state)
        self.assertEqual(run.status, JobStatus.DEAD_LETTER.value)
        self.assertEqual(state.status, JobStatus.DEAD_LETTER.value)
        self.assertIn("mem://missing", run.failure_reason)
        self.assertEqual(run.retry_count, 2)
        self.assertEqual(self.queue.dlq_count, 1)

    def test_broken_document_retries_then_projects_failed_document_state(self) -> None:
        self.connector.put("mem://broken", b"%PDF-not-supported-by-text-parser")
        run = self.worker.enqueue(
            self._message(
                key="broken-doc",
                ref="mem://broken",
                content_type="application/pdf",
            )
        )

        self.worker.drain(max_messages=4)

        run = self.runs.get(run.ingestion_run_id)
        state = self.runs.processing_state("tenant_a", "doc1")
        self.assertIsNotNone(run)
        self.assertIsNotNone(state)
        self.assertEqual(run.status, JobStatus.DEAD_LETTER.value)
        self.assertEqual(state.status, JobStatus.DEAD_LETTER.value)
        self.assertIn("visual async document analyzer is not configured", state.failure_reason)
        self.assertTrue(state.content_checksum)
        self.assertEqual(state.parser_version, "visual-document-analysis-v1")
        self.assertEqual(self.queue.dlq_count, 1)

    def test_pdf_worker_uses_fake_async_visual_analyzer_and_indexes_visual_chunks(self) -> None:
        self.connector.put("mem://manual.pdf", b"%PDF fixture bytes")
        analyzer = FakeAsyncDocumentAnalyzer(
            pages=(
                page_with_text(
                    text="PDF page 1 pump alarm AL-41",
                    page_number=1,
                    tenant_id="tenant_a",
                    collection_id="manuals",
                    document_id="doc1",
                ),
                page_with_text(
                    text="PDF page 2 pump alarm AL-42",
                    page_number=2,
                    tenant_id="tenant_a",
                    collection_id="manuals",
                    document_id="doc1",
                ),
            )
        )
        worker = IngestionWorker(
            queue=self.queue,
            connector=self.connector,
            ingestion=self.sys.ingestion,
            runs=self.runs,
            executor=IngestionExecutor(
                self.sys.ingestion,
                async_document_analyzer=analyzer,
            ),
        )
        run = worker.enqueue(
            self._message(
                key="pdf-ok",
                ref="mem://manual.pdf",
                content_type="application/pdf",
            )
        )

        worker.drain()

        run = self.runs.get(run.ingestion_run_id)
        state = self.runs.processing_state("tenant_a", "doc1")
        doc = self.sys.registry.get("tenant_a", "doc1")
        self.assertIsNotNone(run)
        self.assertIsNotNone(state)
        self.assertIsNotNone(doc)
        self.assertEqual(run.status, JobStatus.SUCCEEDED.value)
        self.assertEqual(run.async_provider, "fake_document_ai")
        self.assertEqual(run.async_job_status, "SUCCEEDED")
        self.assertEqual(state.parser_version, "visual-document-analysis-v1")
        self.assertEqual(doc.metadata["async_provider"], "fake_document_ai")
        self.assertTrue(doc.metadata["visual_asset_ids"][0].startswith("asset_p1_"))
        visual_chunks = [
            chunk
            for chunk, _vector in self.sys.store.iter_items()
            if chunk.document_id == "doc1"
        ]
        self.assertEqual(
            {chunk.metadata["asset_id"] for chunk in visual_chunks},
            set(doc.metadata["visual_asset_ids"]),
        )
        self.assertTrue(
            all(
                chunk.metadata["region_id"].startswith(chunk.metadata["asset_id"])
                for chunk in visual_chunks
            )
        )
        self.assertEqual(worker.stats.processed, 1)


if __name__ == "__main__":
    unittest.main()
