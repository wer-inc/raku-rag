from __future__ import annotations

import unittest

from raku_rag.domain.models import JobStatus
from raku_rag.services.sync import (
    DiffAction,
    DiffDecisionService,
    PipelineVersions,
    SourceDocumentManifest,
)
from raku_rag.workers.ingestion import DocumentProcessingState


class TestSyncDecisionService(unittest.TestCase):
    def setUp(self) -> None:
        self.versions = PipelineVersions(
            parser_version="parser-v1",
            chunking_config_version="chunk-v1",
            embedding_model_version="embed-v1",
        )
        self.service = DiffDecisionService(self.versions)
        self.manifest = SourceDocumentManifest(
            tenant_id="t",
            collection_id="c",
            source_id="s",
            source_document_id="sd1",
            document_id="d1",
            content_checksum="content-1",
            approval_metadata_checksum="meta-1",
        )
        self.state = DocumentProcessingState(
            tenant_id="t",
            collection_id="c",
            source_id="s",
            document_id="d1",
            ingestion_run_id="ing1",
            status=JobStatus.SUCCEEDED.value,
            content_checksum="content-1",
            parser_version="parser-v1",
            chunking_config_version="chunk-v1",
            embedding_model_version="embed-v1",
        )

    def test_unchanged_content_and_versions_skips_pipeline(self) -> None:
        decision = self.service.decide(self.manifest, processing_state=self.state)

        self.assertEqual(decision.action, DiffAction.SKIP)
        self.assertFalse(decision.requires_parse)
        self.assertFalse(decision.requires_embedding)

    def test_approval_metadata_only_change_updates_filters_without_embedding(self) -> None:
        current = SourceDocumentManifest(
            tenant_id="t",
            collection_id="c",
            source_id="s",
            source_document_id="sd1",
            document_id="d1",
            content_checksum="content-1",
            approval_metadata_checksum="meta-2",
        )

        decision = self.service.decide(
            current,
            previous_manifest=self.manifest,
            processing_state=self.state,
        )

        self.assertEqual(decision.action, DiffAction.METADATA_ONLY)
        self.assertTrue(decision.requires_metadata_update)
        self.assertFalse(decision.requires_parse)
        self.assertFalse(decision.requires_embedding)

    def test_parser_version_change_reparse_rechunk_reembed(self) -> None:
        current = SourceDocumentManifest(
            tenant_id="t",
            collection_id="c",
            source_id="s",
            source_document_id="sd1",
            document_id="d1",
            content_checksum="content-1",
            parser_version="parser-v2",
        )

        decision = self.service.decide(current, processing_state=self.state)

        self.assertEqual(decision.action, DiffAction.REPARSE_RECHUNK)
        self.assertEqual(decision.reason, "parser_version_change")
        self.assertTrue(decision.requires_parse)
        self.assertTrue(decision.requires_chunk)
        self.assertTrue(decision.requires_embedding)

    def test_chunking_version_change_reparse_rechunk_reembed(self) -> None:
        current = SourceDocumentManifest(
            tenant_id="t",
            collection_id="c",
            source_id="s",
            source_document_id="sd1",
            document_id="d1",
            content_checksum="content-1",
            chunking_config_version="chunk-v2",
        )

        decision = self.service.decide(current, processing_state=self.state)

        self.assertEqual(decision.action, DiffAction.REPARSE_RECHUNK)
        self.assertEqual(decision.reason, "chunking_config_change")

    def test_embedding_version_change_marks_reembedding_backfill_only(self) -> None:
        current = SourceDocumentManifest(
            tenant_id="t",
            collection_id="c",
            source_id="s",
            source_document_id="sd1",
            document_id="d1",
            content_checksum="content-1",
            embedding_model_version="embed-v2",
        )

        decision = self.service.decide(current, processing_state=self.state)

        self.assertEqual(decision.action, DiffAction.REEMBED)
        self.assertTrue(decision.requires_embedding)
        self.assertTrue(decision.requires_vector_index)
        self.assertFalse(decision.requires_parse)

    def test_deleted_in_source_tombstones_immediately(self) -> None:
        current = SourceDocumentManifest(
            tenant_id="t",
            collection_id="c",
            source_id="s",
            source_document_id="sd1",
            document_id="d1",
            content_checksum="content-1",
            deleted_in_source=True,
        )

        decision = self.service.decide(current, processing_state=self.state)

        self.assertEqual(decision.action, DiffAction.DELETE)
        self.assertTrue(decision.deleted_in_source)
        self.assertFalse(decision.requires_raw_artifact)


if __name__ == "__main__":
    unittest.main()
