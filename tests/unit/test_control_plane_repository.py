from __future__ import annotations

import unittest

from raku_rag.domain.models import JobStatus
from raku_rag.persistence.control_plane import (
    AssetMaterializationRef,
    InMemoryControlPlaneStateRepository,
)
from raku_rag.services.reindex import ReindexPlan
from raku_rag.services.sync import SourceDocumentManifest
from raku_rag.workers.ingestion import (
    DocumentProcessingState,
    IngestionJobMessage,
    SourceSyncState,
)


class TestControlPlaneStateRepository(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = InMemoryControlPlaneStateRepository()
        self.message = IngestionJobMessage(
            idempotency_key="sync:1:doc1",
            tenant_id="tenant_a",
            collection_id="manuals",
            source_id="source_a",
            document_id="doc1",
            document_ref="s3://bucket/doc1.txt",
        )

    def test_ingestion_run_and_processing_state_crud(self) -> None:
        run, created = self.repo.create_ingestion_run(
            self.message, trigger="dagster", run_type="scheduled_sync"
        )
        run.dagster_run_id = "dagster-run-1"
        self.repo.ingestion_runs.mark_running(run)
        self.repo.ingestion_runs.mark_succeeded(
            run,
            chunk_count=2,
            content_checksum="checksum-1",
            parser_version="parser-v1",
            chunking_config_version="chunk-v1",
            embedding_model_version="embed-v1",
        )

        fetched = self.repo.get_ingestion_run("tenant_a", run.ingestion_run_id)
        state = self.repo.processing_state("tenant_a", "doc1")
        runs = self.repo.list_ingestion_runs("tenant_a", source_id="source_a")

        self.assertTrue(created)
        self.assertEqual(fetched.status, JobStatus.SUCCEEDED.value)
        self.assertEqual(state.content_checksum, "checksum-1")
        self.assertEqual(len(runs), 1)

    def test_source_manifest_asset_ref_reindex_plan_and_projection(self) -> None:
        run, _ = self.repo.create_ingestion_run(
            self.message, trigger="dagster", run_type="scheduled_sync"
        )
        run.dagster_run_id = "dagster-run-1"
        self.repo.ingestion_runs.mark_succeeded(
            run,
            chunk_count=2,
            content_checksum="checksum-1",
            parser_version="parser-v1",
            chunking_config_version="chunk-v1",
            embedding_model_version="embed-v1",
        )
        manifest = SourceDocumentManifest(
            tenant_id="tenant_a",
            collection_id="manuals",
            source_id="source_a",
            source_document_id="source-doc-1",
            document_id="doc1",
            content_checksum="checksum-1",
        )
        self.repo.upsert_source_document_manifest(manifest)
        self.repo.upsert_source_sync_state(
            SourceSyncState(
                tenant_id="tenant_a",
                collection_id="manuals",
                source_id="source_a",
                status="idle",
                last_manifest_checksum="manifest-1",
                last_ingestion_run_id=run.ingestion_run_id,
                observed_count=1,
                changed_count=1,
            )
        )
        self.repo.record_asset_materialization(
            AssetMaterializationRef(
                tenant_id="tenant_a",
                collection_id="manuals",
                source_id="source_a",
                sync_run_id="sync-1",
                dagster_asset_key="vector_index_entries",
                partition_key="tenant_a/manuals/source_a/sync-1",
                document_id="doc1",
                chunk_ids=("doc1:0", "doc1:1"),
                storage_uri="s3://artifacts/vector/doc1",
                dagster_run_id="dagster-run-1",
            )
        )
        plan = ReindexPlan(
            reindex_plan_id="reindex-1",
            tenant_id="tenant_a",
            collection_id="manuals",
            scope={"document_ids": ["doc1"]},
        )
        self.repo.create_reindex_plan(plan)

        projection = self.repo.source_sync_status(
            "tenant_a",
            "source_a",
            dagster_base_url="https://dagster.example",
        )
        projected = projection.to_dict()

        self.assertEqual(
            self.repo.source_document_manifest("tenant_a", "source_a", "source-doc-1"), manifest
        )
        self.assertEqual(
            len(self.repo.list_asset_materializations("tenant_a", source_id="source_a")), 1
        )
        self.assertEqual(self.repo.reindex_plan("tenant_a", "reindex-1"), plan)
        self.assertEqual(projected["summary"]["changed_count"], 1)
        self.assertEqual(projected["documents"][0]["source_document_id"], "source-doc-1")
        self.assertEqual(projected["documents"][0]["index_status"], JobStatus.SUCCEEDED.value)
        self.assertEqual(
            projected["asset_materializations"][0]["dagster_asset_key"], "vector_index_entries"
        )
        self.assertEqual(projected["dagster_run_url"], "https://dagster.example/runs/dagster-run-1")

    def test_processing_state_can_be_upserted_without_ingestion_run(self) -> None:
        state = DocumentProcessingState(
            tenant_id="tenant_a",
            collection_id="manuals",
            source_id="source_a",
            document_id="doc2",
            ingestion_run_id="ing_missing",
            status=JobStatus.FAILED.value,
            failure_reason="parser failed",
        )

        self.repo.upsert_processing_state(state)

        states = self.repo.list_processing_states("tenant_a", source_id="source_a")
        self.assertEqual(states[0].document_id, "doc2")
        self.assertEqual(states[0].failure_reason, "parser failed")

    def test_postgres_run_store_exposes_source_sync_status_projection(self) -> None:
        from raku_rag.persistence.postgres import PostgresIngestionRunStore

        for method in (
            "source_sync_status",
            "list_processing_states",
            "list_source_document_manifests",
            "list_asset_materializations",
        ):
            self.assertTrue(
                callable(getattr(PostgresIngestionRunStore, method, None)),
                f"PostgresIngestionRunStore must expose {method}",
            )


if __name__ == "__main__":
    unittest.main()
