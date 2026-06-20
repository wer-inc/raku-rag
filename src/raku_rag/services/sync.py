"""T045 - source manifest diff decisions for ingestion sync.

The real Dagster assets use these rules as their resource boundary. Keeping the decision logic
stdlib-only makes it available to the SQS path, tests, and future Dagster jobs without another
implementation of checksum/version handling.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
from typing import Iterable, Mapping, Protocol

from raku_rag.domain.models import JobStatus


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProcessingStateLike(Protocol):
    status: str
    content_checksum: str
    parser_version: str
    chunking_config_version: str
    embedding_model_version: str


@dataclass(frozen=True)
class PipelineVersions:
    parser_version: str = "text-parser-v1"
    chunking_config_version: str = "sentence-chunker-v1"
    embedding_model_version: str = ""


@dataclass
class SourceDocumentManifest:
    tenant_id: str
    collection_id: str
    source_id: str
    source_document_id: str
    document_id: str = ""
    source_uri: str = ""
    document_ref: str = ""
    content_type: str = "text/plain"
    content_checksum: str = ""
    approval_metadata_checksum: str = ""
    parser_version: str = ""
    chunking_config_version: str = ""
    embedding_model_version: str = ""
    deleted_in_source: bool = False
    observed_at: str = field(default_factory=_now)
    metadata: dict = field(default_factory=dict)

    @property
    def target_document_id(self) -> str:
        return self.document_id or self.source_document_id

    @property
    def fetch_ref(self) -> str:
        return self.document_ref or self.source_uri

    def stable_payload(self) -> dict:
        return {
            "tenant_id": self.tenant_id,
            "collection_id": self.collection_id,
            "source_id": self.source_id,
            "source_document_id": self.source_document_id,
            "document_id": self.target_document_id,
            "source_uri": self.source_uri,
            "document_ref": self.document_ref,
            "content_type": self.content_type,
            "content_checksum": self.content_checksum,
            "approval_metadata_checksum": self.approval_metadata_checksum,
            "parser_version": self.parser_version,
            "chunking_config_version": self.chunking_config_version,
            "embedding_model_version": self.embedding_model_version,
            "deleted_in_source": self.deleted_in_source,
            "metadata": self.metadata,
        }


def manifest_checksum(manifests: Iterable[SourceDocumentManifest]) -> str:
    payload = [m.stable_payload() for m in manifests]
    payload.sort(key=lambda p: (p["tenant_id"], p["source_id"], p["source_document_id"]))
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class DiffAction(str, Enum):
    SKIP = "skip"
    METADATA_ONLY = "metadata_only"
    INGEST = "ingest"
    REPARSE_RECHUNK = "reparse_rechunk"
    REEMBED = "reembed"
    DELETE = "delete"


@dataclass(frozen=True)
class DiffDecision:
    manifest: SourceDocumentManifest
    action: DiffAction
    reason: str
    requires_raw_artifact: bool = False
    requires_parse: bool = False
    requires_chunk: bool = False
    requires_embedding: bool = False
    requires_vector_index: bool = False
    requires_metadata_update: bool = False
    deleted_in_source: bool = False

    @property
    def changed(self) -> bool:
        return self.action not in {DiffAction.SKIP, DiffAction.DELETE}


@dataclass(frozen=True)
class ManifestObservation:
    current: SourceDocumentManifest
    previous: SourceDocumentManifest | None = None


@dataclass(frozen=True)
class SourceSyncPlan:
    decisions: tuple[DiffDecision, ...]
    manifest_checksum: str
    observed_count: int
    changed_count: int
    deleted_count: int
    skipped_count: int
    metadata_only_count: int
    reparse_count: int
    reembedding_count: int


class DiffDecisionService:
    def __init__(self, versions: PipelineVersions | None = None) -> None:
        self.versions = versions or PipelineVersions()

    def decide(
        self,
        manifest: SourceDocumentManifest,
        *,
        previous_manifest: SourceDocumentManifest | None = None,
        processing_state: ProcessingStateLike | None = None,
    ) -> DiffDecision:
        if manifest.deleted_in_source:
            return DiffDecision(
                manifest=manifest,
                action=DiffAction.DELETE,
                reason="deleted_in_source",
                deleted_in_source=True,
            )

        versions = self._effective_versions(manifest)
        if not manifest.content_checksum:
            return self._full_ingest(manifest, "missing_content_checksum")
        if processing_state is None:
            return self._full_ingest(manifest, "new_document")

        state_status = getattr(processing_state, "status", "")
        if state_status != JobStatus.SUCCEEDED.value:
            return self._full_ingest(manifest, "not_successfully_indexed")

        prior_checksum = getattr(processing_state, "content_checksum", "") or ""
        if not prior_checksum:
            return self._full_ingest(manifest, "missing_prior_content_checksum")
        if prior_checksum != manifest.content_checksum:
            return self._full_ingest(manifest, "content_checksum_change")

        prior_parser = getattr(processing_state, "parser_version", "") or ""
        if prior_parser != versions.parser_version:
            return self._reparse(manifest, "parser_version_change")

        prior_chunking = getattr(processing_state, "chunking_config_version", "") or ""
        if prior_chunking != versions.chunking_config_version:
            return self._reparse(manifest, "chunking_config_change")

        prior_embedding = getattr(processing_state, "embedding_model_version", "") or ""
        if prior_embedding != versions.embedding_model_version:
            return DiffDecision(
                manifest=manifest,
                action=DiffAction.REEMBED,
                reason="embedding_model_change",
                requires_embedding=True,
                requires_vector_index=True,
            )

        if (
            previous_manifest is not None
            and previous_manifest.approval_metadata_checksum != manifest.approval_metadata_checksum
        ):
            return DiffDecision(
                manifest=manifest,
                action=DiffAction.METADATA_ONLY,
                reason="approval_metadata_checksum_change",
                requires_metadata_update=True,
            )

        return DiffDecision(manifest=manifest, action=DiffAction.SKIP, reason="unchanged")

    def _effective_versions(self, manifest: SourceDocumentManifest) -> PipelineVersions:
        return PipelineVersions(
            parser_version=manifest.parser_version or self.versions.parser_version,
            chunking_config_version=manifest.chunking_config_version
            or self.versions.chunking_config_version,
            embedding_model_version=manifest.embedding_model_version
            or self.versions.embedding_model_version,
        )

    def _full_ingest(self, manifest: SourceDocumentManifest, reason: str) -> DiffDecision:
        return DiffDecision(
            manifest=manifest,
            action=DiffAction.INGEST,
            reason=reason,
            requires_raw_artifact=True,
            requires_parse=True,
            requires_chunk=True,
            requires_embedding=True,
            requires_vector_index=True,
        )

    def _reparse(self, manifest: SourceDocumentManifest, reason: str) -> DiffDecision:
        return DiffDecision(
            manifest=manifest,
            action=DiffAction.REPARSE_RECHUNK,
            reason=reason,
            requires_raw_artifact=True,
            requires_parse=True,
            requires_chunk=True,
            requires_embedding=True,
            requires_vector_index=True,
        )


@dataclass
class InMemorySourceManifestStore:
    """Small repository used by tests and Dagster-compatible asset shims."""

    _manifests: dict[tuple[str, str, str], SourceDocumentManifest] = field(default_factory=dict)

    def get(
        self, tenant_id: str, source_id: str, source_document_id: str
    ) -> SourceDocumentManifest | None:
        return self._manifests.get((tenant_id, source_id, source_document_id))

    def observe(self, manifest: SourceDocumentManifest) -> ManifestObservation:
        key = (manifest.tenant_id, manifest.source_id, manifest.source_document_id)
        previous = self._manifests.get(key)
        self._manifests[key] = manifest
        return ManifestObservation(current=manifest, previous=previous)

    def list_source(self, tenant_id: str, source_id: str) -> tuple[SourceDocumentManifest, ...]:
        return tuple(
            m for (t, s, _), m in self._manifests.items() if t == tenant_id and s == source_id
        )


def plan_source_sync(
    observations: Iterable[ManifestObservation],
    *,
    processing_states: Mapping[str, ProcessingStateLike | None],
    versions: PipelineVersions | None = None,
    decision_service: DiffDecisionService | None = None,
) -> SourceSyncPlan:
    observations_tuple = tuple(observations)
    service = decision_service or DiffDecisionService(versions)
    decisions = tuple(
        service.decide(
            obs.current,
            previous_manifest=obs.previous,
            processing_state=processing_states.get(obs.current.target_document_id),
        )
        for obs in observations_tuple
    )
    return SourceSyncPlan(
        decisions=decisions,
        manifest_checksum=manifest_checksum(obs.current for obs in observations_tuple),
        observed_count=len(observations_tuple),
        changed_count=sum(1 for d in decisions if d.changed),
        deleted_count=sum(1 for d in decisions if d.action == DiffAction.DELETE),
        skipped_count=sum(1 for d in decisions if d.action == DiffAction.SKIP),
        metadata_only_count=sum(1 for d in decisions if d.action == DiffAction.METADATA_ONLY),
        reparse_count=sum(1 for d in decisions if d.action == DiffAction.REPARSE_RECHUNK),
        reembedding_count=sum(1 for d in decisions if d.action == DiffAction.REEMBED),
    )
