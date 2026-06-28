from __future__ import annotations

import hashlib
import unittest
from unittest.mock import patch

from raku_rag.app import MvpSystem
from raku_rag.domain.models import JobStatus
from raku_rag.persistence.datasources import InMemoryDataSourceRepository
from raku_rag.providers.connectors import FileConnector, MemoryConnector
from raku_rag.providers.mock.visual import FakeAsyncDocumentAnalyzer, page_with_text
from raku_rag.providers.task_queue import InMemoryMessageQueue
from raku_rag.services.datasource_sync import SyncDocument
from raku_rag.persistence.secret_store import InMemorySecretStore
from raku_rag.services.source_sync import SourceSyncService
from raku_rag.workers.ingestion import (
    IngestionExecutor,
    IngestionJobMessage,
    IngestionRunStore,
    IngestionWorker,
)


class TestSourceSyncWorker(unittest.TestCase):
    def test_worker_processes_source_sync_message(self) -> None:
        system = MvpSystem()
        runs = IngestionRunStore()
        secrets = InMemorySecretStore()
        repo = InMemoryDataSourceRepository(secrets)
        repo.upsert(
            "tenant_a",
            "url_main",
            {
                "collection_id": "manuals",
                "type": "object_storage",
                "config": {"source_type": "url", "target_url": "https://example.com/manual"},
            },
        )
        service = SourceSyncService(
            system=system,
            runs=runs,
            datasource_repo=repo,
            secret_store=secrets,
        )
        response, message, created = service.request_source_sync(
            tenant_id="tenant_a",
            source_id="url_main",
            body={"collection_id": "manuals"},
            requested_by="operator",
        )
        self.assertTrue(created)
        self.assertEqual(response["status"], "queued")

        queue = InMemoryMessageQueue()
        queue.enqueue_message(message.to_dict())
        worker = IngestionWorker(
            queue=queue,
            connector=FileConnector(),
            ingestion=system.ingestion,
            runs=runs,
            source_sync_service=service,
        )
        with patch(
            "raku_rag.services.source_sync.build_sync_documents",
            return_value=[
                SyncDocument(
                    document_id="doc_from_url",
                    document_ref="https://example.com/manual",
                    raw=b"line one. line two.",
                    content_type="text/plain",
                )
            ],
        ):
            self.assertTrue(worker.process_once())

        state = runs.source_sync_state("tenant_a", "url_main")
        self.assertIsNotNone(state)
        self.assertEqual(state.status, "succeeded")
        self.assertEqual(state.changed_count, 1)
        self.assertIsNotNone(system.registry.get("tenant_a", "doc_from_url"))
        self.assertEqual(worker.stats.processed, 1)

    def test_source_sync_enqueues_pdf_child_and_finalizes_parent_after_child_completes(self) -> None:
        runs = IngestionRunStore()

        class QueueingVisualSystem(MvpSystem):
            def __init__(self) -> None:
                super().__init__()
                self.ingestion_runs = runs

            def ingest_document(
                self,
                *,
                tenant_id: str,
                collection_id: str,
                source_id: str,
                document_id: str,
                document_ref: str,
                raw: bytes,
                content_type: str = "text/plain",
                manufacturing_metadata=None,
            ):
                message = IngestionJobMessage(
                    idempotency_key=(
                        "api:"
                        f"{collection_id}:{source_id}:{document_id}:"
                        f"{hashlib.sha256(raw).hexdigest()}"
                    ),
                    tenant_id=tenant_id,
                    collection_id=collection_id,
                    source_id=source_id,
                    document_id=document_id,
                    document_ref=document_ref,
                    content_type=content_type,
                )
                run, _ = self.ingestion_runs.create_queued(message, trigger="api")
                return run

        system = QueueingVisualSystem()
        secrets = InMemorySecretStore()
        repo = InMemoryDataSourceRepository(secrets)
        repo.upsert(
            "tenant_a",
            "drive_main",
            {
                "collection_id": "manuals",
                "type": "object_storage",
                "config": {"source_type": "s3"},
            },
        )
        queue = InMemoryMessageQueue()
        connector = MemoryConnector()
        service = SourceSyncService(
            system=system,
            runs=runs,
            datasource_repo=repo,
            secret_store=secrets,
            child_queue=queue,
            connector=connector,
        )
        _response, message, _created = service.request_source_sync(
            tenant_id="tenant_a",
            source_id="drive_main",
            body={"collection_id": "manuals"},
            requested_by="operator",
        )
        queue.enqueue_message(message.to_dict())
        worker = IngestionWorker(
            queue=queue,
            connector=connector,
            ingestion=system.ingestion,
            runs=runs,
            executor=IngestionExecutor(
                system.ingestion,
                async_document_analyzer=FakeAsyncDocumentAnalyzer(
                    pages=(
                        page_with_text(
                            text="PDF page 1 pump alarm AL-42",
                            page_number=1,
                            tenant_id="tenant_a",
                            collection_id="manuals",
                            document_id="manual_pdf",
                        ),
                    )
                ),
            ),
            source_sync_service=service,
        )
        with patch(
            "raku_rag.services.source_sync.build_sync_documents",
            return_value=[
                SyncDocument(
                    document_id="manual_pdf",
                    document_ref="https://example.com/manual.pdf",
                    raw=b"%PDF fixture bytes",
                    content_type="application/pdf",
                )
            ],
        ):
            self.assertTrue(worker.process_once())

        syncing = runs.source_sync_state("tenant_a", "drive_main")
        self.assertIsNotNone(syncing)
        self.assertEqual(syncing.status, "syncing")
        self.assertEqual(queue.available_count, 1)
        child = next(
            run
            for run in runs.list_runs("tenant_a", source_id="drive_main")
            if run.document_id == "manual_pdf"
        )
        self.assertEqual(child.status, JobStatus.QUEUED.value)
        self.assertTrue(child.document_ref.startswith("mem://source-sync/tenant_a/manuals/"))
        self.assertIn(child.document_ref, connector.objects)

        self.assertTrue(worker.process_once())

        final = runs.source_sync_state("tenant_a", "drive_main")
        parent = runs.get(final.last_ingestion_run_id)
        child = runs.get(child.ingestion_run_id)
        self.assertIsNotNone(final)
        self.assertIsNotNone(parent)
        self.assertIsNotNone(child)
        self.assertEqual(final.status, JobStatus.SUCCEEDED.value)
        self.assertEqual(final.changed_count, 1)
        self.assertEqual(parent.status, JobStatus.SUCCEEDED.value)
        self.assertEqual(child.status, JobStatus.SUCCEEDED.value)
        self.assertIsNotNone(system.registry.get("tenant_a", "manual_pdf"))


if __name__ == "__main__":
    unittest.main()
