from __future__ import annotations

from dataclasses import dataclass
import unittest

from raku_rag.dagster.assets.ingestion import (
    DagsterIngestionContext,
    changed_document_manifest,
    source_manifest,
)
from raku_rag.dagster.assets.manufacturing import manufacturing_metadata_enriched_elements
from raku_rag.dagster.checks.manufacturing import manufacturing_quality_checks
from raku_rag.domain.models import Chunk, JobStatus, Modality
from raku_rag.services.sync import InMemorySourceManifestStore, SourceDocumentManifest
from raku_rag.workers.ingestion import DocumentProcessingState

from tests.manufacturing.helpers import T, mfg_meta


@dataclass(frozen=True)
class Citation:
    cell_range: tuple[int, int, int, int] | None = None


class ManufacturingDagsterAssetsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.context = DagsterIngestionContext(
            tenant_id=T,
            collection_id="manuals",
            source_id="source_a",
            sync_run_id="sync_1",
            dagster_run_id="dagster_1",
        )

    def test_metadata_asset_attaches_manufacturing_and_approval_filters_to_chunks(self) -> None:
        chunk = Chunk(
            tenant_id=T,
            collection_id="manuals",
            document_id="doc_a",
            chunk_id="chunk_a",
            text="press alarm E-142 reset procedure",
            position=0,
            token_count=5,
            modality=Modality.TEXT,
        )
        result = manufacturing_metadata_enriched_elements(
            self.context,
            [chunk],
            {"doc_a": mfg_meta(tenant_id=T, document_id="doc_a", equipment_id="EQ-PRESS-100")},
            approval_metadata_checksums={"doc_a": "approval-v2"},
        )

        self.assertEqual(result[0].approval_metadata_checksum, "approval-v2")
        self.assertEqual(result[0].updated_chunk_count, 1)
        self.assertEqual(chunk.metadata["approval_status"], "approved")
        self.assertEqual(chunk.metadata["equipment_id"], "EQ-PRESS-100")
        self.assertIn("_mfg_meta", chunk.metadata)

    def test_metadata_only_approval_checksum_change_updates_safety_and_index_filters(self) -> None:
        store = InMemorySourceManifestStore()
        old = SourceDocumentManifest(
            tenant_id=T,
            collection_id="manuals",
            source_id="source_a",
            source_document_id="doc_a",
            document_id="doc_a",
            content_checksum="body-v1",
            approval_metadata_checksum="approval-v1",
        )
        new = SourceDocumentManifest(
            tenant_id=T,
            collection_id="manuals",
            source_id="source_a",
            source_document_id="doc_a",
            document_id="doc_a",
            content_checksum="body-v1",
            approval_metadata_checksum="approval-v2",
        )
        source_manifest(self.context, [old], store)
        second = source_manifest(self.context, [new], store)
        state = DocumentProcessingState(
            tenant_id=T,
            document_id="doc_a",
            ingestion_run_id="ing_1",
            status=JobStatus.SUCCEEDED.value,
            content_checksum="body-v1",
            parser_version="text-parser-v1",
            chunking_config_version="sentence-chunker-v1",
        )
        changed = changed_document_manifest(second, processing_states={"doc_a": state})

        result = manufacturing_metadata_enriched_elements(
            self.context,
            [],
            {"doc_a": {"approval_status": "obsolete", "effective_date": "2025-01-01"}},
            metadata_only_decisions=changed.decisions,
        )

        self.assertEqual(result[0].document_id, "doc_a")
        self.assertTrue(result[0].metadata_update_only)
        self.assertTrue(result[0].safety_filter_updated)
        self.assertTrue(result[0].index_filter_updated)

    def test_manufacturing_quality_check_bundle_covers_required_hard_gates(self) -> None:
        checks = manufacturing_quality_checks(
            safety_decisions=[
                {
                    "query_id": "q1",
                    "high_risk": True,
                    "approved_effective_citation_present": True,
                }
            ],
            acl_leakage_count=0,
            tenant_isolation_leakage_count=0,
            deleted_document_ids=("deleted",),
            retrieved_document_ids=("live",),
            citations=(Citation((1, 1, 1, 2)),),
            metrics={"recall_at_k": 0.9, "citation_accuracy": 0.8},
            baseline_metrics={"recall_at_k": 0.9, "citation_accuracy": 0.8},
        )

        self.assertEqual(len(checks), 6)
        self.assertTrue(all(check.passed for check in checks))
        self.assertIn(
            "manufacturing_high_risk_approved_citation_requirement",
            {check.name for check in checks},
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
