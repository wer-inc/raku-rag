from __future__ import annotations

import hashlib
import unittest

from raku_rag.app import MvpSystem
from raku_rag.dagster.assets.ingestion import (
    DagsterIngestionContext,
    apply_metadata_only_updates,
    apply_source_deletions,
    changed_document_manifest,
    raw_document_artifacts,
    source_manifest,
    vector_index_entries,
)
from raku_rag.domain.models import JobStatus
from raku_rag.providers.connectors import MemoryConnector
from raku_rag.services.sync import DiffAction, InMemorySourceManifestStore, SourceDocumentManifest
from raku_rag.workers.ingestion import IngestionExecutor, IngestionRunStore


def _checksum(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


class TestDagsterIngestionAssets(unittest.TestCase):
    def setUp(self) -> None:
        self.sys = MvpSystem()
        self.connector = MemoryConnector()
        self.manifests = InMemorySourceManifestStore()
        self.runs = IngestionRunStore()
        self.executor = IngestionExecutor(self.sys.ingestion)
        self.context = DagsterIngestionContext(
            tenant_id="tenant_a",
            collection_id="manuals",
            source_id="source_a",
            sync_run_id="sync_1",
            dagster_run_id="dagster_1",
        )

    def _manifest(
        self,
        raw: bytes,
        *,
        approval_metadata_checksum: str = "meta-1",
        deleted_in_source: bool = False,
        metadata: dict | None = None,
    ) -> SourceDocumentManifest:
        return SourceDocumentManifest(
            tenant_id="tenant_a",
            collection_id="manuals",
            source_id="source_a",
            source_document_id="source-doc-1",
            document_id="doc1",
            document_ref="mem://doc1",
            content_checksum=_checksum(raw),
            approval_metadata_checksum=approval_metadata_checksum,
            deleted_in_source=deleted_in_source,
            metadata=metadata or {},
        )

    def test_asset_pipeline_indexes_new_document_and_projects_processing_state(self) -> None:
        raw = b"Pump P-12 inspection interval is ninety days."
        self.connector.put("mem://doc1", raw)

        manifest_asset = source_manifest(self.context, [self._manifest(raw)], self.manifests)
        changed = changed_document_manifest(manifest_asset, processing_states={})

        self.assertEqual(changed.decisions[0].action, DiffAction.INGEST)

        artifacts = raw_document_artifacts(changed, self.connector)
        entries = vector_index_entries(self.context, artifacts, self.executor, self.runs)
        state = self.runs.processing_state("tenant_a", "doc1")

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].status, JobStatus.SUCCEEDED.value)
        self.assertIsNotNone(state)
        self.assertEqual(state.status, JobStatus.SUCCEEDED.value)
        self.assertEqual(state.content_checksum, _checksum(raw))
        self.assertEqual(state.parser_version, "text-parser-v1")
        self.assertEqual(state.embedding_model_version, self.sys.embedder.model_version)

    def test_unchanged_manifest_skips_parse_chunk_embedding(self) -> None:
        raw = b"Pump P-12 inspection interval is ninety days."
        self.connector.put("mem://doc1", raw)
        first = source_manifest(self.context, [self._manifest(raw)], self.manifests)
        entries = vector_index_entries(
            self.context,
            raw_document_artifacts(
                changed_document_manifest(first, processing_states={}), self.connector
            ),
            self.executor,
            self.runs,
        )
        self.assertEqual(entries[0].status, JobStatus.SUCCEEDED.value)

        state = self.runs.processing_state("tenant_a", "doc1")
        second = source_manifest(self.context, [self._manifest(raw)], self.manifests)
        changed = changed_document_manifest(second, processing_states={"doc1": state})

        self.assertEqual(changed.decisions[0].action, DiffAction.SKIP)
        self.assertEqual(raw_document_artifacts(changed, self.connector), ())

    def test_metadata_only_change_updates_document_metadata_and_invalidates_cache(self) -> None:
        raw = b"Pump P-12 inspection interval is ninety days."
        self.connector.put("mem://doc1", raw)
        first = source_manifest(self.context, [self._manifest(raw)], self.manifests)
        vector_index_entries(
            self.context,
            raw_document_artifacts(
                changed_document_manifest(first, processing_states={}), self.connector
            ),
            self.executor,
            self.runs,
        )
        self.sys.cache.put("tenant_a", "answer:doc1", {"text": "old"}, {"doc1"})
        state = self.runs.processing_state("tenant_a", "doc1")
        second_manifest = self._manifest(
            raw,
            approval_metadata_checksum="meta-2",
            metadata={"approval_status": "approved"},
        )

        second = source_manifest(self.context, [second_manifest], self.manifests)
        changed = changed_document_manifest(second, processing_states={"doc1": state})
        updates = apply_metadata_only_updates(changed, self.sys.registry, self.sys.cache)
        doc = self.sys.registry.get("tenant_a", "doc1")

        self.assertEqual(changed.decisions[0].action, DiffAction.METADATA_ONLY)
        self.assertEqual(updates[0].invalidated_cache_entries, 1)
        self.assertIsNone(self.sys.cache.get("tenant_a", "answer:doc1"))
        self.assertEqual(doc.metadata["approval_status"], "approved")

    def test_deleted_in_source_uses_immediate_deletion_tombstone_path(self) -> None:
        raw = b"Pump P-12 inspection interval is ninety days."
        self.connector.put("mem://doc1", raw)
        first = source_manifest(self.context, [self._manifest(raw)], self.manifests)
        vector_index_entries(
            self.context,
            raw_document_artifacts(
                changed_document_manifest(first, processing_states={}), self.connector
            ),
            self.executor,
            self.runs,
        )
        self.sys.cache.put("tenant_a", "retrieval:doc1", ["old"], {"doc1"})
        state = self.runs.processing_state("tenant_a", "doc1")

        deleted = source_manifest(
            self.context,
            [self._manifest(raw, deleted_in_source=True)],
            self.manifests,
        )
        changed = changed_document_manifest(deleted, processing_states={"doc1": state})
        tombstones = apply_source_deletions(changed, self.sys.deletion)
        doc = self.sys.registry.get("tenant_a", "doc1")

        self.assertEqual(changed.decisions[0].action, DiffAction.DELETE)
        self.assertEqual(len(tombstones), 1)
        self.assertGreaterEqual(tombstones[0].result.tombstoned_chunks, 1)
        self.assertIsNone(self.sys.cache.get("tenant_a", "retrieval:doc1"))
        self.assertTrue(doc.tombstone)


if __name__ == "__main__":
    unittest.main()
