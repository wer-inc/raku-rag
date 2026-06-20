from __future__ import annotations

import unittest

from raku_rag.domain.models import JobStatus
from raku_rag.workers.ingestion import IngestionJobMessage, IngestionRunStore
from workers.ingest.dagster.sensors.retry import discover_failed_retry_candidates


class TestRetrySensor(unittest.TestCase):
    def test_failed_dagster_run_is_visible_as_reconciled_retry_candidate(self) -> None:
        store = IngestionRunStore()
        message = IngestionJobMessage(
            idempotency_key="sync:source:doc1",
            tenant_id="tenant_a",
            collection_id="manuals",
            source_id="source_a",
            document_id="doc1",
            document_ref="s3://bucket/doc1.txt",
        )
        run, _ = store.create_queued(message, trigger="dagster", run_type="scheduled_sync")
        run.dagster_run_id = "dagster-run-1"
        store.mark_failed(run, reason="parser failed", retry_count=2)

        candidates = discover_failed_retry_candidates(store, "tenant_a", source_id="source_a")

        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]
        self.assertEqual(candidate.ingestion_run_id, run.ingestion_run_id)
        self.assertEqual(candidate.postgres_status, JobStatus.FAILED.value)
        self.assertEqual(candidate.processing_state_status, JobStatus.FAILED.value)
        self.assertEqual(candidate.dagster_run_id, "dagster-run-1")
        self.assertTrue(candidate.retryable)
        self.assertTrue(candidate.status_reconciled)


if __name__ == "__main__":
    unittest.main()
