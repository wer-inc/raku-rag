from __future__ import annotations

import unittest

from raku_rag.domain.models import JobStatus
from raku_rag.persistence.control_plane import InMemoryControlPlaneStateRepository
from raku_rag.workers.ingestion import SourceSyncState

from tests.manufacturing.helpers import T, claims, fresh


class ManufacturingSyncStatusContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.sys = fresh()
        self.operator = claims(T, "ops", roles=("internal_operator",))
        self.user = claims(T, "user", roles=("viewer",))

    def test_manual_sync_request_returns_202_shape_and_status_url(self) -> None:
        response = self.sys.request_source_sync(
            self.user,
            "source_a",
            collection_id="manuals",
            document_id="doc_a",
            document_ref="mem://doc_a",
        )

        self.assertEqual(response["status"], JobStatus.QUEUED.value)
        self.assertTrue(response["ingestion_run_id"].startswith("ing_"))
        self.assertEqual(
            response["status_url"],
            f"/v1/manufacturing/ingestion-runs/{response['ingestion_run_id']}",
        )

    def test_sync_status_hides_dagster_fields_for_non_internal_operator(self) -> None:
        response = self.sys.request_source_sync(
            self.user,
            "source_a",
            collection_id="manuals",
            document_id="doc_a",
        )
        run = self.sys.control_plane.get_ingestion_run(T, response["ingestion_run_id"])
        self.assertIsNotNone(run)
        run.dagster_run_id = "dagster_secret"
        self.sys.control_plane.upsert_source_sync_state(
            SourceSyncState(
                tenant_id=T,
                source_id="source_a",
                collection_id="manuals",
                status="syncing",
                last_ingestion_run_id=run.ingestion_run_id,
                observed_count=1,
                changed_count=1,
            )
        )

        viewer_payload = self.sys.source_sync_status(self.user, "source_a")
        operator_payload = self.sys.source_sync_status(self.operator, "source_a")

        self.assertNotIn("dagster_run_id", viewer_payload)
        self.assertIn("manufacturing_metadata", viewer_payload)
        self.assertEqual(operator_payload["dagster_run_id"], "dagster_secret")

    def test_ingestion_run_status_returns_document_processing_summary(self) -> None:
        response = self.sys.request_source_sync(
            self.user,
            "source_a",
            collection_id="manuals",
            document_id="doc_a",
        )
        run = self.sys.control_plane.get_ingestion_run(T, response["ingestion_run_id"])
        self.assertIsNotNone(run)
        self.sys.control_plane.ingestion_runs.mark_running(run)
        self.sys.control_plane.ingestion_runs.mark_succeeded(
            run,
            chunk_count=3,
            content_checksum="checksum",
            parser_version="text-parser-v1",
            chunking_config_version="sentence-chunker-v1",
            embedding_model_version="embed-v1",
        )

        payload = self.sys.ingestion_run_status(self.user, run.ingestion_run_id)

        self.assertEqual(payload["status"], JobStatus.SUCCEEDED.value)
        self.assertEqual(payload["summary"]["succeeded_count"], 1)
        self.assertEqual(payload["documents"][0]["chunk_count"], 3)

    def test_service_can_be_used_with_an_injected_control_plane_repository(self) -> None:
        repo = InMemoryControlPlaneStateRepository()
        sys = fresh()
        sys._sync_status.repository = repo
        response = sys.request_source_sync(self.user, "source_b")
        self.assertIsNotNone(repo.get_ingestion_run(T, response["ingestion_run_id"]))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
