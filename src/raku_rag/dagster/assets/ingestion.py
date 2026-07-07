"""T045a-c - Dagster-compatible ingestion asset helpers.

The MVP does not import Dagster in the hot test path. These functions are intentionally plain Python
so a real Dagster asset can wrap them while SQS/admin flows keep sharing the same sync and ingestion
services.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from typing import Iterable, Mapping

from raku_rag.domain.models import Chunk, Document, JobStatus, Modality
from raku_rag.interfaces.base import (
    Chunker,
    Connector,
    EmbeddingProvider,
    Parser,
    Vector,
    VectorStore,
)
from raku_rag.services.cache import CacheService
from raku_rag.services.deletion import DeletionResult, DeletionService
from raku_rag.services.ingestion import DocumentRegistry
from raku_rag.services.ingestion_quality import (
    accepted_quality_metadata,
    purge_quality_partitioned_document,
)
from raku_rag.services.sync import (
    DiffAction,
    DiffDecision,
    DiffDecisionService,
    InMemorySourceManifestStore,
    ManifestObservation,
    PipelineVersions,
    ProcessingStateLike,
    SourceDocumentManifest,
    SourceSyncPlan,
    plan_source_sync,
)
from raku_rag.workers.ingestion import IngestionExecutor, IngestionJobMessage, IngestionRunStore


@dataclass(frozen=True)
class DagsterIngestionContext:
    tenant_id: str
    collection_id: str
    source_id: str
    sync_run_id: str
    dagster_run_id: str = ""
    tags: dict[str, str] = field(default_factory=dict)

    @property
    def dagster_tags(self) -> dict[str, str]:
        base = {
            "tenant_id": self.tenant_id,
            "collection_id": self.collection_id,
            "source_id": self.source_id,
            "sync_run_id": self.sync_run_id,
        }
        if self.dagster_run_id:
            base["dagster_run_id"] = self.dagster_run_id
        base.update(self.tags)
        return base


@dataclass(frozen=True)
class SourceManifestAsset:
    context: DagsterIngestionContext
    observations: tuple[ManifestObservation, ...]
    manifest_checksum: str


@dataclass(frozen=True)
class ChangedDocumentManifestAsset:
    context: DagsterIngestionContext
    plan: SourceSyncPlan

    @property
    def decisions(self) -> tuple[DiffDecision, ...]:
        return self.plan.decisions


@dataclass(frozen=True)
class RawDocumentArtifact:
    decision: DiffDecision
    raw: bytes
    content_checksum: str

    @property
    def manifest(self) -> SourceDocumentManifest:
        return self.decision.manifest


@dataclass(frozen=True)
class ParsedDocumentElements:
    artifact: RawDocumentArtifact
    text: str


@dataclass(frozen=True)
class ChunkAsset:
    manifest: SourceDocumentManifest
    chunk: Chunk


@dataclass(frozen=True)
class EmbeddingAsset:
    chunk_asset: ChunkAsset
    vector: Vector


@dataclass(frozen=True)
class VectorIndexEntry:
    document_id: str
    ingestion_run_id: str = ""
    chunk_count: int = 0
    status: str = JobStatus.SUCCEEDED.value
    content_checksum: str = ""
    parser_version: str = ""
    chunking_config_version: str = ""
    embedding_model_version: str = ""
    failure_reason: str = ""


@dataclass(frozen=True)
class SourceDeletionTombstone:
    document_id: str
    result: DeletionResult


@dataclass(frozen=True)
class MetadataUpdateResult:
    document_id: str
    invalidated_cache_entries: int = 0
    updated: bool = False


def source_manifest(
    context: DagsterIngestionContext,
    observed_documents: Iterable[SourceDocumentManifest | Mapping[str, object]],
    manifest_store: InMemorySourceManifestStore,
) -> SourceManifestAsset:
    observations = tuple(
        manifest_store.observe(_coerce_manifest(context, item)) for item in observed_documents
    )
    checksum = plan_source_sync(
        observations,
        processing_states={},
        decision_service=DiffDecisionService(),
    ).manifest_checksum
    return SourceManifestAsset(
        context=context, observations=observations, manifest_checksum=checksum
    )


def changed_document_manifest(
    manifest_asset: SourceManifestAsset,
    *,
    processing_states: Mapping[str, ProcessingStateLike | None],
    versions: PipelineVersions | None = None,
    decision_service: DiffDecisionService | None = None,
) -> ChangedDocumentManifestAsset:
    effective_versions = versions or _infer_versions_from_states(processing_states)
    plan = plan_source_sync(
        manifest_asset.observations,
        processing_states=processing_states,
        versions=effective_versions,
        decision_service=decision_service,
    )
    return ChangedDocumentManifestAsset(context=manifest_asset.context, plan=plan)


def apply_source_deletions(
    changed_asset: ChangedDocumentManifestAsset,
    deletion: DeletionService,
) -> tuple[SourceDeletionTombstone, ...]:
    results: list[SourceDeletionTombstone] = []
    for decision in changed_asset.decisions:
        if decision.action != DiffAction.DELETE:
            continue
        manifest = decision.manifest
        result = deletion.delete(manifest.tenant_id, manifest.target_document_id)
        results.append(
            SourceDeletionTombstone(document_id=manifest.target_document_id, result=result)
        )
    return tuple(results)


def apply_metadata_only_updates(
    changed_asset: ChangedDocumentManifestAsset,
    registry: DocumentRegistry,
    cache: CacheService | None = None,
) -> tuple[MetadataUpdateResult, ...]:
    results: list[MetadataUpdateResult] = []
    for decision in changed_asset.decisions:
        if decision.action != DiffAction.METADATA_ONLY:
            continue
        manifest = decision.manifest
        doc = registry.get(manifest.tenant_id, manifest.target_document_id)
        if doc is None:
            results.append(MetadataUpdateResult(document_id=manifest.target_document_id))
            continue
        doc.metadata.update(manifest.metadata)
        invalidated = (
            cache.invalidate_document(manifest.tenant_id, manifest.target_document_id)
            if cache
            else 0
        )
        results.append(
            MetadataUpdateResult(
                document_id=manifest.target_document_id,
                invalidated_cache_entries=invalidated,
                updated=True,
            )
        )
    return tuple(results)


def raw_document_artifacts(
    changed_asset: ChangedDocumentManifestAsset,
    connector: Connector,
) -> tuple[RawDocumentArtifact, ...]:
    artifacts: list[RawDocumentArtifact] = []
    for decision in changed_asset.decisions:
        if not decision.requires_raw_artifact:
            continue
        ref = decision.manifest.fetch_ref
        if not ref:
            raise ValueError(f"missing document_ref for {decision.manifest.target_document_id}")
        raw = connector.fetch(ref)
        artifacts.append(
            RawDocumentArtifact(
                decision=decision,
                raw=raw,
                content_checksum=hashlib.sha256(raw).hexdigest(),
            )
        )
    return tuple(artifacts)


def parsed_document_elements(
    artifacts: Iterable[RawDocumentArtifact],
    parser: Parser,
) -> tuple[ParsedDocumentElements, ...]:
    parsed: list[ParsedDocumentElements] = []
    for artifact in artifacts:
        manifest = artifact.manifest
        if not parser.supports(manifest.content_type):
            raise ValueError(f"unsupported content_type: {manifest.content_type}")
        parsed.append(
            ParsedDocumentElements(
                artifact=artifact, text=parser.parse(artifact.raw, manifest.content_type)
            )
        )
    return tuple(parsed)


def chunks(
    parsed: Iterable[ParsedDocumentElements],
    chunker: Chunker,
    versions: PipelineVersions,
) -> tuple[ChunkAsset, ...]:
    chunk_assets: list[ChunkAsset] = []
    for item in parsed:
        manifest = item.artifact.manifest
        for text_piece, heading, position, span in chunker.chunk(item.text):
            chunk_assets.append(
                ChunkAsset(
                    manifest=manifest,
                    chunk=Chunk(
                        tenant_id=manifest.tenant_id,
                        chunk_id=f"{manifest.target_document_id}:{position}",
                        document_id=manifest.target_document_id,
                        collection_id=manifest.collection_id,
                        text=text_piece,
                        position=position,
                        token_count=len(text_piece.split()),
                        heading_path=heading,
                        modality=Modality.TEXT,
                        embedding_model_version=versions.embedding_model_version,
                        offset_mapping=(span, span[0]),
                        metadata=accepted_quality_metadata(),
                    ),
                )
            )
    return tuple(chunk_assets)


def embeddings(
    chunk_assets: Iterable[ChunkAsset],
    embedder: EmbeddingProvider,
) -> tuple[EmbeddingAsset, ...]:
    assets = tuple(chunk_assets)
    vectors = embedder.embed([asset.chunk.text for asset in assets]) if assets else []
    return tuple(
        EmbeddingAsset(chunk_asset=asset, vector=vector) for asset, vector in zip(assets, vectors)
    )


def materialize_vector_index_entries(
    embedding_assets: Iterable[EmbeddingAsset],
    store: VectorStore,
    registry: DocumentRegistry,
    *,
    content_checksums: Mapping[str, str],
) -> tuple[VectorIndexEntry, ...]:
    grouped: dict[str, list[tuple[Chunk, Vector]]] = {}
    manifests: dict[str, SourceDocumentManifest] = {}
    for asset in embedding_assets:
        manifest = asset.chunk_asset.manifest
        doc_id = manifest.target_document_id
        grouped.setdefault(doc_id, []).append((asset.chunk_asset.chunk, asset.vector))
        manifests[doc_id] = manifest

    entries: list[VectorIndexEntry] = []
    for doc_id, pairs in grouped.items():
        manifest = manifests[doc_id]
        existing = registry.get(manifest.tenant_id, doc_id)
        purge_quality_partitioned_document(store, manifest.tenant_id, doc_id)
        store.upsert(pairs)
        registry.put(
            Document(
                tenant_id=manifest.tenant_id,
                collection_id=manifest.collection_id,
                document_id=doc_id,
                source_id=manifest.source_id,
                version=(existing.version + 1) if existing else 1,
                checksum=content_checksums.get(doc_id, manifest.content_checksum),
                metadata={**accepted_quality_metadata(), **dict(manifest.metadata)},
                created_at=existing.created_at if existing else "",
                updated_at="",
                indexed_at="",
                tombstone=False,
            )
        )
        entries.append(
            VectorIndexEntry(
                document_id=doc_id,
                chunk_count=len(pairs),
                content_checksum=content_checksums.get(doc_id, manifest.content_checksum),
            )
        )
    return tuple(entries)


def vector_index_entries(
    context: DagsterIngestionContext,
    artifacts: Iterable[RawDocumentArtifact],
    executor: IngestionExecutor,
    runs: IngestionRunStore | None = None,
) -> tuple[VectorIndexEntry, ...]:
    """Publish vector entries through the same executor used by SQS workers."""

    entries: list[VectorIndexEntry] = []
    for artifact in artifacts:
        manifest = artifact.manifest
        run = None
        if runs is not None:
            message = IngestionJobMessage(
                idempotency_key=(
                    f"dagster:{context.sync_run_id}:{manifest.source_id}:"
                    f"{manifest.target_document_id}:{artifact.content_checksum}"
                ),
                tenant_id=manifest.tenant_id,
                collection_id=manifest.collection_id,
                source_id=manifest.source_id,
                document_id=manifest.target_document_id,
                document_ref=manifest.fetch_ref,
                content_type=manifest.content_type,
            )
            run, _ = runs.create_queued(message, trigger="dagster", run_type="scheduled_sync")
            runs.mark_running(run)

        result = executor.execute_document(
            tenant_id=manifest.tenant_id,
            collection_id=manifest.collection_id,
            source_id=manifest.source_id,
            document_id=manifest.target_document_id,
            raw=artifact.raw,
            content_type=manifest.content_type,
        )
        if runs is not None and run is not None:
            if result.status == JobStatus.SUCCEEDED.value:
                runs.mark_succeeded(
                    run,
                    chunk_count=result.chunk_count,
                    content_checksum=result.content_checksum,
                    parser_version=result.parser_version,
                    chunking_config_version=result.chunking_config_version,
                    embedding_model_version=result.embedding_model_version,
                )
            else:
                runs.mark_failed(
                    run,
                    reason=result.failure_reason or "ingestion failed",
                    retry_count=0,
                    content_checksum=result.content_checksum,
                    parser_version=result.parser_version,
                    chunking_config_version=result.chunking_config_version,
                    embedding_model_version=result.embedding_model_version,
                )
        entries.append(
            VectorIndexEntry(
                document_id=result.document_id,
                ingestion_run_id=run.ingestion_run_id if run else "",
                chunk_count=result.chunk_count,
                status=result.status,
                content_checksum=result.content_checksum,
                parser_version=result.parser_version,
                chunking_config_version=result.chunking_config_version,
                embedding_model_version=result.embedding_model_version,
                failure_reason=result.failure_reason,
            )
        )
    return tuple(entries)


def _coerce_manifest(
    context: DagsterIngestionContext,
    item: SourceDocumentManifest | Mapping[str, object],
) -> SourceDocumentManifest:
    if isinstance(item, SourceDocumentManifest):
        return item
    data = dict(item)
    source_document_id = str(data.get("source_document_id") or data.get("document_id") or "")
    if not source_document_id:
        raise ValueError("source_document_id is required")
    return SourceDocumentManifest(
        tenant_id=str(data.get("tenant_id") or context.tenant_id),
        collection_id=str(data.get("collection_id") or context.collection_id),
        source_id=str(data.get("source_id") or context.source_id),
        source_document_id=source_document_id,
        document_id=str(data.get("document_id") or source_document_id),
        source_uri=str(data.get("source_uri") or ""),
        document_ref=str(data.get("document_ref") or data.get("source_uri") or ""),
        content_type=str(data.get("content_type") or "text/plain"),
        content_checksum=str(data.get("content_checksum") or ""),
        approval_metadata_checksum=str(data.get("approval_metadata_checksum") or ""),
        parser_version=str(data.get("parser_version") or ""),
        chunking_config_version=str(data.get("chunking_config_version") or ""),
        embedding_model_version=str(data.get("embedding_model_version") or ""),
        deleted_in_source=bool(data.get("deleted_in_source") or False),
        metadata=dict(data.get("metadata") or {}),
    )


def _infer_versions_from_states(
    processing_states: Mapping[str, ProcessingStateLike | None],
) -> PipelineVersions:
    for state in processing_states.values():
        if state is None:
            continue
        embedding_model_version = getattr(state, "embedding_model_version", "") or ""
        if embedding_model_version:
            return PipelineVersions(embedding_model_version=embedding_model_version)
    return PipelineVersions()
