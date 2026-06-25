from __future__ import annotations

import unittest
from unittest.mock import patch

from raku_rag.app import MvpSystem
from raku_rag.persistence.datasources import InMemoryDataSourceRepository
from raku_rag.providers.connectors import FileConnector
from raku_rag.providers.task_queue import InMemoryMessageQueue
from raku_rag.services.datasource_sync import SyncDocument
from raku_rag.persistence.secret_store import InMemorySecretStore
from raku_rag.services.source_sync import SourceSyncService
from raku_rag.workers.ingestion import IngestionRunStore, IngestionWorker


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


if __name__ == "__main__":
    unittest.main()
