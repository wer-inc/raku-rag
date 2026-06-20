"""T021b - app-facing control-plane state repository.

This repository keeps the state shape used by SQS workers, Dagster-compatible assets, and admin APIs
in one place. The production Postgres adapter can mirror these methods while tests use the in-memory
implementation without Docker.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from raku_rag.dagster.run_url import dagster_run_url
from raku_rag.services.reindex import InMemoryReindexPlanStore, ReindexPlan
from raku_rag.services.sync import InMemorySourceManifestStore, SourceDocumentManifest
from raku_rag.workers.ingestion import (
    DocumentProcessingState,
    IngestionJobMessage,
    IngestionRun,
    IngestionRunStore,
    SourceSyncState,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class AssetMaterializationRef:
    tenant_id: str
    collection_id: str
    source_id: str
    sync_run_id: str
    dagster_asset_key: str
    partition_key: str
    asset_materialization_id: str = ""
    document_id: str = ""
    chunk_ids: tuple[str, ...] = ()
    storage_uri: str = ""
    dagster_run_id: str = ""
    created_at: str = field(default_factory=_now)

    def __post_init__(self) -> None:
        if not self.asset_materialization_id:
            object.__setattr__(
                self,
                "asset_materialization_id",
                f"amr:{self.tenant_id}:{self.dagster_asset_key}:{self.partition_key}",
            )


@dataclass(frozen=True)
class DocumentProcessingProjection:
    document_id: str
    source_document_id: str
    content_checksum: str
    parser_version: str
    chunking_config_version: str
    embedding_model_version: str
    parse_status: str
    chunk_status: str
    embedding_status: str
    index_status: str
    last_indexed_at: str = ""
    last_error: str = ""
    dagster_run_id: str = ""

    def to_dict(self) -> dict:
        return {
            "document_id": self.document_id,
            "source_document_id": self.source_document_id,
            "content_checksum": self.content_checksum,
            "parser_version": self.parser_version,
            "chunking_config_version": self.chunking_config_version,
            "embedding_model_version": self.embedding_model_version,
            "parse_status": self.parse_status,
            "chunk_status": self.chunk_status,
            "embedding_status": self.embedding_status,
            "index_status": self.index_status,
            "last_indexed_at": self.last_indexed_at,
            "last_error": self.last_error,
            "dagster_run_id": self.dagster_run_id,
        }


@dataclass(frozen=True)
class SourceSyncStatusProjection:
    tenant_id: str
    source_id: str
    collection_id: str
    status: str
    last_manifest_checksum: str
    summary: dict
    documents: tuple[DocumentProcessingProjection, ...]
    asset_materializations: tuple[AssetMaterializationRef, ...]
    dagster_run_id: str = ""
    dagster_run_url: str = ""
    correlation_id: str = ""

    def to_dict(self) -> dict:
        return {
            "tenant_id": self.tenant_id,
            "source_id": self.source_id,
            "collection_id": self.collection_id,
            "status": self.status,
            "last_manifest_checksum": self.last_manifest_checksum,
            "summary": dict(self.summary),
            "documents": [doc.to_dict() for doc in self.documents],
            "asset_materializations": [
                {
                    "asset_materialization_id": ref.asset_materialization_id,
                    "dagster_asset_key": ref.dagster_asset_key,
                    "partition_key": ref.partition_key,
                    "storage_uri": ref.storage_uri,
                    "document_id": ref.document_id,
                    "chunk_ids": list(ref.chunk_ids),
                }
                for ref in self.asset_materializations
            ],
            "dagster_run_id": self.dagster_run_id,
            "dagster_run_url": self.dagster_run_url,
            "correlation_id": self.correlation_id,
        }


@dataclass
class InMemoryControlPlaneStateRepository:
    ingestion_runs: IngestionRunStore = field(default_factory=IngestionRunStore)
    source_manifests: InMemorySourceManifestStore = field(
        default_factory=InMemorySourceManifestStore
    )
    reindex_plans: InMemoryReindexPlanStore = field(default_factory=InMemoryReindexPlanStore)
    _asset_refs: dict[str, AssetMaterializationRef] = field(default_factory=dict)

    # IngestionRun CRUD -------------------------------------------------------------------------
    def create_ingestion_run(
        self, message: IngestionJobMessage, *, trigger: str = "sqs", run_type: str = "upload_ingest"
    ) -> tuple[IngestionRun, bool]:
        return self.ingestion_runs.create_queued(message, trigger=trigger, run_type=run_type)

    def get_ingestion_run(self, tenant_id: str, ingestion_run_id: str) -> IngestionRun | None:
        run = self.ingestion_runs.get(ingestion_run_id)
        if run is None or run.tenant_id != tenant_id:
            return None
        return run

    def list_ingestion_runs(
        self, tenant_id: str, *, status: str = "", source_id: str = "", limit: int = 50
    ) -> list[IngestionRun]:
        return self.ingestion_runs.list_runs(
            tenant_id, status=status, source_id=source_id, limit=limit
        )

    # DocumentProcessingState CRUD ---------------------------------------------------------------
    def upsert_processing_state(self, state: DocumentProcessingState) -> DocumentProcessingState:
        return self.ingestion_runs.upsert_processing_state(state)

    def processing_state(self, tenant_id: str, document_id: str) -> DocumentProcessingState | None:
        return self.ingestion_runs.processing_state(tenant_id, document_id)

    def list_processing_states(
        self, tenant_id: str, *, collection_id: str = "", source_id: str = ""
    ) -> list[DocumentProcessingState]:
        return self.ingestion_runs.list_processing_states(
            tenant_id, collection_id=collection_id, source_id=source_id
        )

    # SourceSyncState CRUD ----------------------------------------------------------------------
    def upsert_source_sync_state(self, state: SourceSyncState) -> SourceSyncState:
        return self.ingestion_runs.upsert_source_sync_state(state)

    def source_sync_state(self, tenant_id: str, source_id: str) -> SourceSyncState | None:
        return self.ingestion_runs.source_sync_state(tenant_id, source_id)

    # SourceDocumentManifest CRUD ---------------------------------------------------------------
    def upsert_source_document_manifest(
        self, manifest: SourceDocumentManifest
    ) -> SourceDocumentManifest:
        self.source_manifests.observe(manifest)
        return manifest

    def source_document_manifest(
        self, tenant_id: str, source_id: str, source_document_id: str
    ) -> SourceDocumentManifest | None:
        return self.source_manifests.get(tenant_id, source_id, source_document_id)

    def list_source_document_manifests(
        self, tenant_id: str, source_id: str
    ) -> tuple[SourceDocumentManifest, ...]:
        return self.source_manifests.list_source(tenant_id, source_id)

    # AssetMaterializationRef CRUD ---------------------------------------------------------------
    def record_asset_materialization(self, ref: AssetMaterializationRef) -> AssetMaterializationRef:
        self._asset_refs[ref.asset_materialization_id] = ref
        return ref

    def asset_materialization(
        self, asset_materialization_id: str
    ) -> AssetMaterializationRef | None:
        return self._asset_refs.get(asset_materialization_id)

    def list_asset_materializations(
        self, tenant_id: str, *, source_id: str = "", sync_run_id: str = ""
    ) -> tuple[AssetMaterializationRef, ...]:
        refs = [ref for ref in self._asset_refs.values() if ref.tenant_id == tenant_id]
        if source_id:
            refs = [ref for ref in refs if ref.source_id == source_id]
        if sync_run_id:
            refs = [ref for ref in refs if ref.sync_run_id == sync_run_id]
        return tuple(sorted(refs, key=lambda ref: ref.created_at, reverse=True))

    # ReindexPlan CRUD --------------------------------------------------------------------------
    def create_reindex_plan(self, plan: ReindexPlan) -> ReindexPlan:
        return self.reindex_plans.create(plan)

    def reindex_plan(self, tenant_id: str, reindex_plan_id: str) -> ReindexPlan | None:
        return self.reindex_plans.get(tenant_id, reindex_plan_id)

    def list_reindex_plans(self, tenant_id: str, *, collection_id: str = "") -> list[ReindexPlan]:
        return self.reindex_plans.list(tenant_id, collection_id=collection_id)

    # App-facing projection ----------------------------------------------------------------------
    def source_sync_status(
        self,
        tenant_id: str,
        source_id: str,
        *,
        dagster_base_url: str = "",
    ) -> SourceSyncStatusProjection | None:
        state = self.source_sync_state(tenant_id, source_id)
        if state is None:
            return None
        runs = self.list_ingestion_runs(tenant_id, source_id=source_id)
        latest_run = runs[0] if runs else None
        manifests = self.list_source_document_manifests(tenant_id, source_id)
        documents = tuple(self._project_document(manifest, latest_run) for manifest in manifests)
        dagster_run_id = latest_run.dagster_run_id if latest_run else ""
        return SourceSyncStatusProjection(
            tenant_id=state.tenant_id,
            source_id=state.source_id,
            collection_id=state.collection_id,
            status=state.status,
            last_manifest_checksum=state.last_manifest_checksum,
            summary={
                "observed_count": state.observed_count,
                "changed_count": state.changed_count,
                "deleted_count": state.deleted_count,
                "skipped_count": state.skipped_count,
                "failed_count": state.failed_count,
            },
            documents=documents,
            asset_materializations=self.list_asset_materializations(tenant_id, source_id=source_id),
            dagster_run_id=dagster_run_id,
            dagster_run_url=(
                dagster_run_url(dagster_base_url, dagster_run_id)
                if dagster_base_url and dagster_run_id
                else ""
            ),
            correlation_id=state.last_ingestion_run_id,
        )

    def _project_document(
        self, manifest: SourceDocumentManifest, latest_run: IngestionRun | None
    ) -> DocumentProcessingProjection:
        state = self.processing_state(manifest.tenant_id, manifest.target_document_id)
        dagster_run_id = latest_run.dagster_run_id if latest_run else ""
        if state is None:
            return DocumentProcessingProjection(
                document_id=manifest.target_document_id,
                source_document_id=manifest.source_document_id,
                content_checksum=manifest.content_checksum,
                parser_version=manifest.parser_version,
                chunking_config_version=manifest.chunking_config_version,
                embedding_model_version=manifest.embedding_model_version,
                parse_status="pending",
                chunk_status="pending",
                embedding_status="pending",
                index_status="pending",
                dagster_run_id=dagster_run_id,
            )
        return DocumentProcessingProjection(
            document_id=state.document_id,
            source_document_id=manifest.source_document_id,
            content_checksum=state.content_checksum,
            parser_version=state.parser_version,
            chunking_config_version=state.chunking_config_version,
            embedding_model_version=state.embedding_model_version,
            parse_status=state.status,
            chunk_status=state.status,
            embedding_status=state.status,
            index_status=state.status,
            last_indexed_at=state.updated_at if state.status == "succeeded" else "",
            last_error=state.failure_reason,
            dagster_run_id=dagster_run_id,
        )
