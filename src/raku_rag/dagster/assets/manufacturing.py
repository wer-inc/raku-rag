"""Manufacturing Dagster-compatible asset helpers.

These functions are plain Python so tests, SQS workers, and a real Dagster wrapper can share one
implementation. Request-path services may read materialized state, but they do not invoke these
helpers synchronously.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from typing import Iterable, Mapping

from raku_rag.dagster.assets.ingestion import ChunkAsset, DagsterIngestionContext
from raku_rag.domain.models import Chunk, IdentityClaims
from raku_rag.manufacturing.domain.metadata import (
    ApprovalSource,
    ApprovalStatus,
    ManufacturingDocumentMetadata,
)
from raku_rag.manufacturing.ingestion.metadata_enrichment import MFG_META_KEY, MetadataEnricher
from raku_rag.manufacturing.kpi.poc_metrics import PocKpiReport
from raku_rag.manufacturing.telemetry.safety_metrics import SOURCE_AUDIT_LOG, SafetyTelemetry
from raku_rag.services.cache import CacheService
from raku_rag.services.ingestion import DocumentRegistry
from raku_rag.services.sync import DiffAction, DiffDecision


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stable_id(prefix: str, payload: object) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return f"{prefix}_{hashlib.sha256(raw).hexdigest()[:16]}"


@dataclass(frozen=True)
class ManufacturingMetadataEnrichmentResult:
    document_id: str
    chunk_ids: tuple[str, ...]
    approval_metadata_checksum: str
    metadata_update_only: bool = False
    updated_chunk_count: int = 0
    document_metadata_updated: bool = False
    safety_filter_updated: bool = False
    index_filter_updated: bool = False
    invalidated_cache_entries: int = 0
    materialized_at: str = field(default_factory=_now)

    def to_dict(self) -> dict:
        return {
            "document_id": self.document_id,
            "chunk_ids": list(self.chunk_ids),
            "approval_metadata_checksum": self.approval_metadata_checksum,
            "metadata_update_only": self.metadata_update_only,
            "updated_chunk_count": self.updated_chunk_count,
            "document_metadata_updated": self.document_metadata_updated,
            "safety_filter_updated": self.safety_filter_updated,
            "index_filter_updated": self.index_filter_updated,
            "invalidated_cache_entries": self.invalidated_cache_entries,
            "materialized_at": self.materialized_at,
        }


@dataclass(frozen=True)
class ManufacturingDashboardMetricsSnapshot:
    snapshot_id: str
    tenant_id: str
    collection_id: str
    metrics: dict
    safety_telemetry: dict
    materialized_at: str
    source_ingestion_run_id: str = ""
    dagster_run_id: str = ""

    def to_dict(self) -> dict:
        return {
            "snapshot_id": self.snapshot_id,
            "tenant_id": self.tenant_id,
            "collection_id": self.collection_id,
            "metrics": dict(self.metrics),
            "safety_telemetry": dict(self.safety_telemetry),
            "materialized_at": self.materialized_at,
            "source_ingestion_run_id": self.source_ingestion_run_id,
            "dagster_run_id": self.dagster_run_id,
        }


@dataclass
class InMemoryManufacturingKpiMaterializationStore:
    _snapshots: dict[tuple[str, str], ManufacturingDashboardMetricsSnapshot] = field(
        default_factory=dict
    )

    def put(
        self,
        snapshot: ManufacturingDashboardMetricsSnapshot,
    ) -> ManufacturingDashboardMetricsSnapshot:
        key = (snapshot.tenant_id, snapshot.collection_id)
        self._snapshots[key] = snapshot
        return snapshot

    def latest(
        self,
        tenant_id: str,
        collection_id: str = "",
    ) -> ManufacturingDashboardMetricsSnapshot | None:
        if collection_id:
            return self._snapshots.get((tenant_id, collection_id))
        candidates = [
            snapshot
            for (tenant, _collection), snapshot in self._snapshots.items()
            if tenant == tenant_id
        ]
        if not candidates:
            return None
        return sorted(candidates, key=lambda item: item.materialized_at, reverse=True)[0]


def manufacturing_metadata_enriched_elements(
    context: DagsterIngestionContext,
    chunk_assets: Iterable[ChunkAsset | Chunk],
    metadata_by_document: Mapping[str, ManufacturingDocumentMetadata | Mapping[str, object]],
    *,
    approval_metadata_checksums: Mapping[str, str] | None = None,
    metadata_only_decisions: Iterable[DiffDecision] = (),
    enricher: MetadataEnricher | None = None,
    registry: DocumentRegistry | None = None,
    cache: CacheService | None = None,
) -> tuple[ManufacturingMetadataEnrichmentResult, ...]:
    """Attach manufacturing metadata to parsed chunks and handle approval-metadata-only updates."""

    checksums = dict(approval_metadata_checksums or {})
    grouped: dict[str, list[Chunk]] = {}
    for item in chunk_assets:
        chunk = item.chunk if isinstance(item, ChunkAsset) else item
        grouped.setdefault(chunk.document_id, []).append(chunk)

    results: list[ManufacturingMetadataEnrichmentResult] = []
    touched = set()
    for document_id, chunks in grouped.items():
        meta = _coerce_meta(context, document_id, metadata_by_document.get(document_id))
        filter_metadata = _filter_metadata(meta)
        for chunk in chunks:
            chunk.metadata[MFG_META_KEY] = meta
            chunk.metadata.update(filter_metadata)
        updated_doc = _attach_document_metadata(
            context,
            document_id,
            meta,
            registry=registry,
            enricher=enricher,
        )
        touched.add(document_id)
        results.append(
            ManufacturingMetadataEnrichmentResult(
                document_id=document_id,
                chunk_ids=tuple(chunk.chunk_id for chunk in chunks),
                approval_metadata_checksum=checksums.get(
                    document_id,
                    _approval_metadata_checksum(meta),
                ),
                updated_chunk_count=len(chunks),
                document_metadata_updated=updated_doc,
                safety_filter_updated=True,
                index_filter_updated=True,
            )
        )

    for decision in metadata_only_decisions:
        if decision.action != DiffAction.METADATA_ONLY:
            continue
        document_id = decision.manifest.target_document_id
        meta = _coerce_meta(context, document_id, metadata_by_document.get(document_id))
        invalidated = 0
        updated_doc = _attach_document_metadata(
            context,
            document_id,
            meta,
            registry=registry,
            enricher=enricher,
        )
        if registry is not None:
            doc = registry.get(context.tenant_id, document_id)
            if doc is not None:
                doc.metadata.update(_filter_metadata(meta))
                updated_doc = True
        if cache is not None:
            invalidated = cache.invalidate_document(context.tenant_id, document_id)
        if document_id in touched:
            continue
        results.append(
            ManufacturingMetadataEnrichmentResult(
                document_id=document_id,
                chunk_ids=(),
                approval_metadata_checksum=(
                    decision.manifest.approval_metadata_checksum
                    or _approval_metadata_checksum(meta)
                ),
                metadata_update_only=True,
                updated_chunk_count=0,
                document_metadata_updated=updated_doc,
                safety_filter_updated=True,
                index_filter_updated=True,
                invalidated_cache_entries=invalidated,
            )
        )

    return tuple(results)


def manufacturing_dashboard_metrics(
    context: DagsterIngestionContext,
    *,
    audit,
    principal: IdentityClaims,
    iter_meta,
    telemetry: SafetyTelemetry | None = None,
    collection_id: str | None = None,
    source_ingestion_run_id: str = "",
    store: InMemoryManufacturingKpiMaterializationStore | None = None,
) -> ManufacturingDashboardMetricsSnapshot:
    """Materialize FR-MFG-028 KPI + safety telemetry for dashboard reads."""

    effective_collection = collection_id if collection_id is not None else context.collection_id
    effective_telemetry = telemetry or SafetyTelemetry(audit)
    report = PocKpiReport.compute(
        audit=audit,
        telemetry=effective_telemetry,
        principal=principal,
        iter_meta=iter_meta,
        collection_id=effective_collection,
    )
    telemetry_view = effective_telemetry.compute(
        principal=principal,
        collection_id=effective_collection,
    )
    materialized_at = _now()
    snapshot = ManufacturingDashboardMetricsSnapshot(
        snapshot_id=_stable_id(
            "mfg_kpi_snapshot",
            [
                context.tenant_id,
                effective_collection,
                report.to_json(),
                source_ingestion_run_id,
                context.dagster_run_id,
            ],
        ),
        tenant_id=context.tenant_id,
        collection_id=effective_collection or "",
        metrics=report.to_json(),
        safety_telemetry={
            "tenant_id": telemetry_view.tenant_id,
            "high_risk_query_count": telemetry_view.high_risk_query_count,
            "safety_gate_block_count": telemetry_view.safety_gate_block_count,
            "block_breakdown": dict(telemetry_view.block_breakdown),
            "source": SOURCE_AUDIT_LOG,
        },
        materialized_at=materialized_at,
        source_ingestion_run_id=source_ingestion_run_id,
        dagster_run_id=context.dagster_run_id,
    )
    if store is not None:
        store.put(snapshot)
    return snapshot


def _attach_document_metadata(
    context: DagsterIngestionContext,
    document_id: str,
    meta: ManufacturingDocumentMetadata,
    *,
    registry: DocumentRegistry | None,
    enricher: MetadataEnricher | None,
) -> bool:
    updated = False
    if registry is not None:
        doc = registry.get(context.tenant_id, document_id)
        if doc is not None:
            doc.metadata[MFG_META_KEY] = meta
            doc.metadata.update(_filter_metadata(meta))
            updated = True
    if enricher is not None:
        enricher.attach(context.tenant_id, document_id, meta)
        updated = True
    return updated


def _coerce_meta(
    context: DagsterIngestionContext,
    document_id: str,
    raw: ManufacturingDocumentMetadata | Mapping[str, object] | None,
) -> ManufacturingDocumentMetadata:
    if isinstance(raw, ManufacturingDocumentMetadata):
        return raw
    data = dict(raw or {})
    data.setdefault("tenant_id", context.tenant_id)
    data.setdefault("document_id", document_id)
    if isinstance(data.get("approval_status"), str):
        data["approval_status"] = ApprovalStatus(str(data["approval_status"]))
    if isinstance(data.get("approval_source"), str):
        data["approval_source"] = ApprovalSource(str(data["approval_source"]))
    return ManufacturingDocumentMetadata(**data)


def _filter_metadata(meta: ManufacturingDocumentMetadata) -> dict:
    return {
        "tenant_id": meta.tenant_id,
        "document_id": meta.document_id,
        "process_id": meta.process_id or "",
        "equipment_id": meta.equipment_id or "",
        "alarm_code": meta.alarm_code or "",
        "defect_type": meta.defect_type or "",
        "part_no": meta.part_no or "",
        "customer": meta.customer or "",
        "document_kind": meta.document_kind.value if meta.document_kind else "",
        "approval_status": meta.approval_status.value,
        "approval_source": meta.approval_source.value,
        "effective_date": meta.effective_date or "",
        "safety_category": meta.safety_category or "",
        "quality_category": meta.quality_category or "",
        "hazard_tags": list(meta.hazard_tags),
    }


def _approval_metadata_checksum(meta: ManufacturingDocumentMetadata) -> str:
    payload = {
        "approval_status": meta.approval_status.value,
        "approval_source": meta.approval_source.value,
        "effective_date": meta.effective_date,
        "valid_until": meta.valid_until,  # 0017-A: an expiry-only change MUST be re-propagated
        "approved_by": meta.approved_by,
        "approved_at": meta.approved_at,
        "obsolete_at": meta.obsolete_at,
        "superseded_by": meta.superseded_by,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


__all__ = [
    "InMemoryManufacturingKpiMaterializationStore",
    "ManufacturingDashboardMetricsSnapshot",
    "ManufacturingMetadataEnrichmentResult",
    "manufacturing_dashboard_metrics",
    "manufacturing_metadata_enriched_elements",
]
