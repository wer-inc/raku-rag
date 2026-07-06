"""Queue-driven ingestion worker.

This module wraps the existing 001 ``IngestionService`` with the production-track concerns that do
not belong in parse/chunk/embed itself: SQS-style messages, idempotency, run status projection, and
document processing state.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
import hashlib
from io import BytesIO
from typing import Protocol

from raku_rag.domain.models import BoundingBox, Document, JobStatus, LayoutRegion, VisualAsset
from raku_rag.interfaces.base import Connector, Vector
from raku_rag.interfaces.visual import (
    AsyncDocumentAnalyzer,
    AsyncJobStatus,
    AsyncSubmitRequest,
    CaptioningProvider,
    DocumentAnalysis,
    IngestContext,
    JobHandle,
    LayoutExtractor,
    OcrEngine,
)
from raku_rag.observability.redaction import Redactor
from raku_rag.providers.captioning import CaptioningResult, DeterministicCaptioningProvider
from raku_rag.providers.embeddings import embedding_dimension
from raku_rag.providers.layout import DeterministicLayoutExtractor
from raku_rag.providers.ocr import DeterministicOcrEngine
from raku_rag.providers.task_queue import QueueEnvelope
from raku_rag.providers.visual_embeddings import HashingVisualEmbeddingProvider
from raku_rag.services.cost import CostService
from raku_rag.services.crop import CropService
from raku_rag.services.ingestion import IngestionService, PII_REDACTION_POLICY_REF
from raku_rag.services.ingestion_quality import (
    quality_metadata_from_ocr_metadata,
    with_quality_metadata,
)

VISUAL_REGION_REDACTION_REQUIRED_REF = "visual-region-redaction-required"
ASYNC_ANALYSIS_RETRY_DELAY_SECONDS = 300


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class IngestionJobMessage:
    idempotency_key: str
    tenant_id: str
    collection_id: str
    source_id: str
    document_id: str
    document_ref: str
    content_type: str = "text/plain"

    def to_dict(self) -> dict:
        return {
            "idempotency_key": self.idempotency_key,
            "tenant_id": self.tenant_id,
            "collection_id": self.collection_id,
            "source_id": self.source_id,
            "document_id": self.document_id,
            "document_ref": self.document_ref,
            "content_type": self.content_type,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "IngestionJobMessage":
        required = (
            "idempotency_key",
            "tenant_id",
            "collection_id",
            "source_id",
            "document_id",
            "document_ref",
        )
        missing = [k for k in required if not data.get(k)]
        if missing:
            raise ValueError(f"missing ingestion message fields: {', '.join(missing)}")
        return cls(
            idempotency_key=str(data["idempotency_key"]),
            tenant_id=str(data["tenant_id"]),
            collection_id=str(data["collection_id"]),
            source_id=str(data["source_id"]),
            document_id=str(data["document_id"]),
            document_ref=str(data["document_ref"]),
            content_type=str(data.get("content_type") or "text/plain"),
        )


@dataclass(frozen=True)
class SourceSyncJobMessage:
    idempotency_key: str
    tenant_id: str
    collection_id: str
    source_id: str
    sync_run_id: str
    scope: dict = field(default_factory=dict)
    requested_by: str = ""
    force: bool = False

    def to_dict(self) -> dict:
        return {
            "job_type": "source_sync",
            "idempotency_key": self.idempotency_key,
            "tenant_id": self.tenant_id,
            "collection_id": self.collection_id,
            "source_id": self.source_id,
            "sync_run_id": self.sync_run_id,
            "scope": dict(self.scope),
            "requested_by": self.requested_by,
            "force": self.force,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SourceSyncJobMessage":
        required = ("idempotency_key", "tenant_id", "collection_id", "source_id", "sync_run_id")
        missing = [k for k in required if not data.get(k)]
        if missing:
            raise ValueError(f"missing source sync message fields: {', '.join(missing)}")
        scope = data.get("scope") if isinstance(data.get("scope"), dict) else {}
        return cls(
            idempotency_key=str(data["idempotency_key"]),
            tenant_id=str(data["tenant_id"]),
            collection_id=str(data["collection_id"]),
            source_id=str(data["source_id"]),
            sync_run_id=str(data["sync_run_id"]),
            scope=dict(scope),
            requested_by=str(data.get("requested_by") or ""),
            force=bool(data.get("force")),
        )


@dataclass
class IngestionRun:
    ingestion_run_id: str
    idempotency_key: str
    tenant_id: str
    collection_id: str
    source_id: str
    document_id: str
    document_ref: str
    content_type: str
    type: str = "upload_ingest"
    trigger: str = "sqs"
    status: str = JobStatus.QUEUED.value
    failure_reason: str = ""
    chunk_count: int = 0
    retry_count: int = 0
    sqs_message_id: str = ""
    dagster_run_id: str = ""
    async_provider: str = ""
    async_job_id: str = ""
    async_job_status: str = ""
    started_at: str = ""
    finished_at: str = ""
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)


@dataclass
class DocumentProcessingState:
    tenant_id: str
    document_id: str
    ingestion_run_id: str
    collection_id: str = ""
    source_id: str = ""
    status: str = JobStatus.QUEUED.value
    content_checksum: str = ""
    parser_version: str = ""
    chunking_config_version: str = ""
    embedding_model_version: str = ""
    chunk_count: int = 0
    failure_reason: str = ""
    updated_at: str = field(default_factory=_now)


@dataclass
class SourceSyncState:
    tenant_id: str
    source_id: str
    collection_id: str
    status: str = "idle"
    last_manifest_checksum: str = ""
    last_ingestion_run_id: str = ""
    observed_count: int = 0
    changed_count: int = 0
    deleted_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0
    last_synced_at: str = ""
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)


class MessageQueue(Protocol):
    def enqueue_message(self, body: dict) -> str: ...

    def receive(self, max_messages: int = 1) -> list[QueueEnvelope]: ...

    def ack(self, envelope: QueueEnvelope) -> None: ...

    def fail(self, envelope: QueueEnvelope, reason: str) -> bool: ...

    def retry_later(
        self, envelope: QueueEnvelope, *, delay_seconds: int = 5, reason: str = ""
    ) -> None: ...


@dataclass
class IngestionRunStore:
    """In-memory run/status projection.

    The shape mirrors the Postgres tables in the production migration so API and worker code can be
    ported to a database-backed repository without changing behavior.
    """

    _runs: dict[str, IngestionRun] = field(default_factory=dict)
    _by_key: dict[tuple[str, str], str] = field(default_factory=dict)
    _states: dict[tuple[str, str], DocumentProcessingState] = field(default_factory=dict)
    _sync_states: dict[tuple[str, str], SourceSyncState] = field(default_factory=dict)
    _seq: int = 0

    def create_queued(
        self, message: IngestionJobMessage, *, trigger: str = "sqs", run_type: str = "upload_ingest"
    ) -> tuple[IngestionRun, bool]:
        key = (message.tenant_id, message.idempotency_key)
        if key in self._by_key:
            return self._runs[self._by_key[key]], False
        self._seq += 1
        run = IngestionRun(
            ingestion_run_id=f"ing_{self._seq}",
            idempotency_key=message.idempotency_key,
            tenant_id=message.tenant_id,
            collection_id=message.collection_id,
            source_id=message.source_id,
            document_id=message.document_id,
            document_ref=message.document_ref,
            content_type=message.content_type,
            type=run_type,
            trigger=trigger,
        )
        self._runs[run.ingestion_run_id] = run
        self._by_key[key] = run.ingestion_run_id
        self._states[(message.tenant_id, message.document_id)] = DocumentProcessingState(
            tenant_id=message.tenant_id,
            document_id=message.document_id,
            ingestion_run_id=run.ingestion_run_id,
            collection_id=message.collection_id,
            source_id=message.source_id,
        )
        return run, True

    def get(self, ingestion_run_id: str) -> IngestionRun | None:
        return self._runs.get(ingestion_run_id)

    def get_for_tenant(self, tenant_id: str, ingestion_run_id: str) -> IngestionRun | None:
        run = self.get(ingestion_run_id)
        if run is None or run.tenant_id != tenant_id:
            return None
        return run

    def get_by_idempotency_key(self, tenant_id: str, idempotency_key: str) -> IngestionRun | None:
        run_id = self._by_key.get((tenant_id, idempotency_key))
        return self._runs.get(run_id) if run_id else None

    def processing_state(self, tenant_id: str, document_id: str) -> DocumentProcessingState | None:
        return self._states.get((tenant_id, document_id))

    def upsert_processing_state(self, state: DocumentProcessingState) -> DocumentProcessingState:
        state.updated_at = _now()
        self._states[(state.tenant_id, state.document_id)] = state
        return state

    def list_processing_states(
        self, tenant_id: str, *, collection_id: str = "", source_id: str = ""
    ) -> list[DocumentProcessingState]:
        states = [state for (t, _), state in self._states.items() if t == tenant_id]
        if collection_id:
            states = [state for state in states if state.collection_id == collection_id]
        if source_id:
            states = [state for state in states if state.source_id == source_id]
        return sorted(states, key=lambda state: state.updated_at, reverse=True)

    def list_runs(
        self,
        tenant_id: str,
        *,
        status: str = "",
        source_id: str = "",
        limit: int = 50,
    ) -> list[IngestionRun]:
        runs = [run for run in self._runs.values() if run.tenant_id == tenant_id]
        if status:
            runs = [run for run in runs if run.status == status]
        if source_id:
            runs = [run for run in runs if run.source_id == source_id]
        runs = sorted(runs, key=lambda run: run.created_at, reverse=True)
        return runs[: max(1, min(limit, 200))]

    def upsert_source_sync_state(self, state: SourceSyncState) -> SourceSyncState:
        state.updated_at = _now()
        self._sync_states[(state.tenant_id, state.source_id)] = state
        return state

    def source_sync_state(self, tenant_id: str, source_id: str) -> SourceSyncState | None:
        state = self._sync_states.get((tenant_id, source_id))
        if state is not None:
            return state
        runs = self.list_runs(tenant_id, source_id=source_id)
        if not runs:
            return None
        latest = runs[0]
        status = {
            JobStatus.QUEUED.value: "queued",
            JobStatus.RUNNING.value: "syncing",
            JobStatus.FAILED.value: "failed",
            JobStatus.DEAD_LETTER.value: "failed",
        }.get(latest.status, "idle")
        return SourceSyncState(
            tenant_id=tenant_id,
            source_id=source_id,
            collection_id=latest.collection_id,
            status=status,
            last_ingestion_run_id=latest.ingestion_run_id,
            observed_count=len(runs),
            changed_count=sum(1 for run in runs if run.status == JobStatus.SUCCEEDED.value),
            failed_count=sum(
                1
                for run in runs
                if run.status in {JobStatus.FAILED.value, JobStatus.DEAD_LETTER.value}
            ),
            last_synced_at=next(
                (run.finished_at for run in runs if run.status == JobStatus.SUCCEEDED.value),
                "",
            ),
            created_at=latest.created_at,
            updated_at=latest.updated_at,
        )

    def mark_message_id(self, run: IngestionRun, message_id: str) -> None:
        run.sqs_message_id = message_id
        run.updated_at = _now()

    def mark_queued(self, run: IngestionRun) -> None:
        run.status = JobStatus.QUEUED.value
        run.failure_reason = ""
        run.sqs_message_id = ""
        run.finished_at = ""
        run.updated_at = _now()
        self._mark_state(run, JobStatus.QUEUED.value)

    def mark_async_job(self, run: IngestionRun, *, provider: str, job_id: str, status: str) -> None:
        run.async_provider = provider
        run.async_job_id = job_id
        run.async_job_status = status
        run.updated_at = _now()

    def mark_running(self, run: IngestionRun) -> None:
        run.status = JobStatus.RUNNING.value
        run.started_at = run.started_at or _now()
        run.updated_at = _now()
        self._mark_state(run, JobStatus.RUNNING.value)

    def mark_succeeded(
        self,
        run: IngestionRun,
        *,
        chunk_count: int,
        content_checksum: str = "",
        parser_version: str = "",
        chunking_config_version: str = "",
        embedding_model_version: str = "",
    ) -> None:
        run.status = JobStatus.SUCCEEDED.value
        run.failure_reason = ""
        run.chunk_count = chunk_count
        run.finished_at = _now()
        run.updated_at = run.finished_at
        self._mark_state(
            run,
            JobStatus.SUCCEEDED.value,
            chunk_count=chunk_count,
            content_checksum=content_checksum,
            parser_version=parser_version,
            chunking_config_version=chunking_config_version,
            embedding_model_version=embedding_model_version,
        )

    def mark_partially_succeeded(
        self,
        run: IngestionRun,
        *,
        reason: str,
        chunk_count: int,
        content_checksum: str = "",
        parser_version: str = "",
        chunking_config_version: str = "",
        embedding_model_version: str = "",
    ) -> None:
        run.status = "partially_succeeded"
        run.failure_reason = reason
        run.chunk_count = chunk_count
        run.finished_at = _now()
        run.updated_at = run.finished_at
        self._mark_state(
            run,
            "partially_succeeded",
            chunk_count=chunk_count,
            failure_reason=reason,
            content_checksum=content_checksum,
            parser_version=parser_version,
            chunking_config_version=chunking_config_version,
            embedding_model_version=embedding_model_version,
        )

    def mark_failed(
        self,
        run: IngestionRun,
        *,
        reason: str,
        retry_count: int,
        content_checksum: str = "",
        parser_version: str = "",
        chunking_config_version: str = "",
        embedding_model_version: str = "",
    ) -> None:
        run.status = JobStatus.FAILED.value
        run.failure_reason = reason
        run.retry_count = retry_count
        run.finished_at = _now()
        run.updated_at = run.finished_at
        self._mark_state(
            run,
            JobStatus.FAILED.value,
            failure_reason=reason,
            content_checksum=content_checksum,
            parser_version=parser_version,
            chunking_config_version=chunking_config_version,
            embedding_model_version=embedding_model_version,
        )

    def mark_dead_letter(
        self,
        run: IngestionRun,
        *,
        reason: str,
        retry_count: int,
        content_checksum: str = "",
        parser_version: str = "",
        chunking_config_version: str = "",
        embedding_model_version: str = "",
    ) -> None:
        run.status = JobStatus.DEAD_LETTER.value
        run.failure_reason = reason
        run.retry_count = retry_count
        run.finished_at = _now()
        run.updated_at = run.finished_at
        self._mark_state(
            run,
            JobStatus.DEAD_LETTER.value,
            failure_reason=reason,
            content_checksum=content_checksum,
            parser_version=parser_version,
            chunking_config_version=chunking_config_version,
            embedding_model_version=embedding_model_version,
        )

    def _mark_state(
        self,
        run: IngestionRun,
        status: str,
        *,
        chunk_count: int = 0,
        failure_reason: str = "",
        content_checksum: str = "",
        parser_version: str = "",
        chunking_config_version: str = "",
        embedding_model_version: str = "",
    ) -> None:
        state = self._states[(run.tenant_id, run.document_id)]
        state.status = status
        state.chunk_count = chunk_count
        state.failure_reason = failure_reason
        if content_checksum:
            state.content_checksum = content_checksum
        if parser_version:
            state.parser_version = parser_version
        if chunking_config_version:
            state.chunking_config_version = chunking_config_version
        if embedding_model_version:
            state.embedding_model_version = embedding_model_version
        state.updated_at = _now()


@dataclass
class IngestionWorkerStats:
    processed: int = 0
    skipped_duplicates: int = 0
    failed: int = 0
    dead_lettered: int = 0


@dataclass(frozen=True)
class IngestionExecutionResult:
    status: str
    document_id: str
    chunk_count: int = 0
    failure_reason: str = ""
    skipped: bool = False
    content_checksum: str = ""
    parser_version: str = ""
    chunking_config_version: str = ""
    embedding_model_version: str = ""
    async_provider: str = ""
    async_job_id: str = ""
    async_job_status: str = ""


@dataclass(frozen=True)
class VisualIngestionOptions:
    captioning_enabled: bool = True
    content_type: str = "image/png"


def _ocr_quality_review_threshold() -> float:
    import os

    raw = os.environ.get("RAKU_OCR_CONFIDENCE_REVIEW_THRESHOLD") or ""
    try:
        value = float(raw)
    except ValueError:
        value = 90.0
    return value if 0 < value <= 100 else 90.0


def _ocr_quality_metadata(results: tuple["VisualIngestionResult", ...]) -> dict:
    confidences = [
        float(region.transcription_confidence)
        for result in results
        for region in result.regions
        if region.transcription_confidence is not None and not region.metadata.get("page_aggregate")
    ]
    if not confidences:
        return {}
    threshold = _ocr_quality_review_threshold()
    minimum = min(confidences)
    return {
        "ocr_confidence_mean": round(sum(confidences) / len(confidences), 2),
        "ocr_confidence_min": round(minimum, 2),
        "ocr_quality_review_required": minimum < threshold,
        "ocr_quality_review_threshold": threshold,
    }


@dataclass(frozen=True)
class VisualIngestionResult:
    asset: VisualAsset
    regions: tuple[LayoutRegion, ...]
    visual_vectors: tuple[Vector, ...]
    caption_status: str
    caption_failure_reason: str = ""
    exif_removed_keys: tuple[str, ...] = ()


class VisualIngestionExecutor:
    """Reusable image/scanned-PDF ingestion boundary for US6.

    The executor is deterministic for local tests but mirrors the production stages: EXIF strip,
    visual asset creation, OCR, layout regions, optional captioning, visual embeddings, and visual
    cost records.
    """

    def __init__(
        self,
        *,
        ocr: OcrEngine | None = None,
        layout: LayoutExtractor | None = None,
        captioning: CaptioningProvider | None = None,
        visual_embedder: HashingVisualEmbeddingProvider | None = None,
        redactor: Redactor | None = None,
        cost: CostService | None = None,
        crops: CropService | None = None,
    ) -> None:
        self.ocr = ocr or DeterministicOcrEngine()
        self.layout = layout or DeterministicLayoutExtractor(self.ocr)
        self.captioning = captioning or DeterministicCaptioningProvider()
        self.visual_embedder = visual_embedder or HashingVisualEmbeddingProvider()
        self.redactor = redactor or Redactor()
        self.cost = cost
        self.crops = crops

    def execute_image(
        self,
        *,
        tenant_id: str,
        collection_id: str,
        source_id: str,
        document_id: str,
        image: bytes,
        exif_metadata: dict | None = None,
        options: VisualIngestionOptions | None = None,
        job_id: str = "",
        trace_id: str = "",
    ) -> VisualIngestionResult:
        options = options or VisualIngestionOptions()
        checksum = hashlib.sha256(image).hexdigest()
        asset_id = f"asset_{checksum[:12]}"
        exif = self.redactor.redact_exif(exif_metadata or {})
        asset = VisualAsset(
            tenant_id=tenant_id,
            collection_id=collection_id,
            document_id=document_id,
            asset_id=asset_id,
            storage_uri=f"memory://visual-assets/{tenant_id}/{asset_id}",
            checksum=checksum,
            content_type=options.content_type,
            metadata={
                "source_id": source_id,
                "exif": exif.metadata,
                "exif_removed_keys": list(exif.removed_keys),
                "visual_embedding_model_version": self.visual_embedder.model_version,
            },
        )
        self._record_visual_cost(
            tenant_id,
            "visual_storage_cost",
            collection_id=collection_id,
            job_id=job_id,
            trace_id=trace_id,
            quantity=len(image),
            unit="bytes",
        )

        raw_ocr_regions = self.ocr.extract(
            image,
            tenant_id=tenant_id,
            collection_id=collection_id,
            document_id=document_id,
            asset_id=asset_id,
        )
        ocr_sensitive_labels = tuple(
            _sensitive_labels(self.redactor, region.text) for region in raw_ocr_regions
        )
        ocr_regions = tuple(
            replace(region, text=self.redactor.redact_visual_text(region.text))
            for region in raw_ocr_regions
        )
        self._record_visual_cost(
            tenant_id,
            "ocr_cost",
            collection_id=collection_id,
            job_id=job_id,
            trace_id=trace_id,
            quantity=len(ocr_regions),
            unit="regions",
        )
        regions = self.layout.extract(
            image,
            tenant_id=tenant_id,
            collection_id=collection_id,
            document_id=document_id,
            asset_id=asset_id,
            ocr_regions=ocr_regions,
        )
        self._record_visual_cost(
            tenant_id,
            "layout_extraction_cost",
            collection_id=collection_id,
            job_id=job_id,
            trace_id=trace_id,
            quantity=len(regions),
            unit="regions",
        )

        caption_result = CaptioningResult(status="not_requested")
        if options.captioning_enabled:
            caption_result = self.captioning.caption(
                image,
                tenant_id=tenant_id,
                collection_id=collection_id,
                document_id=document_id,
                asset_id=asset_id,
                content_type=options.content_type,
            )
            self._record_visual_cost(
                tenant_id,
                "captioning_cost",
                collection_id=collection_id,
                job_id=job_id,
                trace_id=trace_id,
                quantity=1,
                unit="request",
            )
            if caption_result.status == "succeeded":
                regions = tuple(
                    replace(
                        region,
                        generated_caption_text=caption_result.generated_caption_text,
                        caption_source=caption_result.caption_source,
                    )
                    for region in regions
                )
        regions = tuple(
            replace(
                region,
                metadata={
                    **_visual_region_provenance_metadata(region),
                    **_visual_region_redaction_metadata(
                        region,
                        ocr_labels=(
                            ocr_sensitive_labels[idx] if idx < len(ocr_sensitive_labels) else ()
                        ),
                        caption_labels=caption_result.sensitive_detection_labels,
                    ),
                },
            )
            for idx, region in enumerate(regions)
        )
        regions = _append_page_aggregate_regions(
            regions,
            tenant_id=tenant_id,
            collection_id=collection_id,
            document_id=document_id,
            asset_id=asset_id,
        )
        regions = self._materialize_crops(
            regions,
            raw_bytes=image,
            content_type=options.content_type,
        )

        embedding_inputs = [
            f"{region.ocr_text}\n{region.generated_caption_text}".encode("utf-8")
            for region in regions
        ]
        if hasattr(self.visual_embedder, "policy_resolver"):
            raw_vectors = self.visual_embedder.embed(
                embedding_inputs,
                tenant_id=tenant_id,
                collection_id=collection_id,
                document_id=document_id,
            )
        else:
            raw_vectors = self.visual_embedder.embed(embedding_inputs)
        vectors = tuple(tuple(vec) for vec in raw_vectors)
        self._record_visual_cost(
            tenant_id,
            "visual_embedding_cost",
            collection_id=collection_id,
            job_id=job_id,
            trace_id=trace_id,
            quantity=len(vectors),
            unit="regions",
        )
        return VisualIngestionResult(
            asset=asset,
            regions=tuple(regions),
            visual_vectors=vectors,
            caption_status=caption_result.status,
            caption_failure_reason=caption_result.failure_reason,
            exif_removed_keys=exif.removed_keys,
        )

    def execute_document_analysis(
        self,
        *,
        tenant_id: str,
        collection_id: str,
        source_id: str,
        document_id: str,
        document_ref: str,
        analysis: DocumentAnalysis,
        job_id: str = "",
        trace_id: str = "",
    ) -> tuple[VisualIngestionResult, ...]:
        """Convert neutral async document analysis into page-scoped visual ingestion results."""

        results: list[VisualIngestionResult] = []
        for page in analysis.pages:
            raw_regions = page.layout_regions or tuple(
                LayoutRegion(
                    tenant_id=tenant_id,
                    collection_id=collection_id,
                    document_id=document_id,
                    asset_id=f"asset_p{page.page_number}",
                    region_id=f"asset_p{page.page_number}:region:{idx}",
                    bbox=ocr.bbox,
                    page_number=page.page_number,
                    region_type="text",
                    heading_path=("visual",),
                    ocr_text=ocr.text,
                    extraction_source=ocr.extraction_source,
                    transcription_confidence=ocr.confidence,
                )
                for idx, ocr in enumerate(page.ocr_regions, start=1)
            )
            page_text = "\n".join(region.ocr_text for region in raw_regions)
            checksum = hashlib.sha256(
                f"{document_ref}:{page.page_number}:{page_text}".encode("utf-8")
            ).hexdigest()
            asset_id = f"asset_p{page.page_number}_{checksum[:8]}"
            asset = VisualAsset(
                tenant_id=tenant_id,
                collection_id=collection_id,
                document_id=document_id,
                asset_id=asset_id,
                storage_uri=document_ref,
                checksum=checksum,
                content_type="application/pdf-page",
                page_number=page.page_number,
                metadata={
                    "source_id": source_id,
                    "async_provider": analysis.provider,
                    "async_job_id": analysis.job_id,
                    "extractor_version": analysis.metadata.get("extractor_version", ""),
                    "visual_embedding_model_version": self.visual_embedder.model_version,
                },
            )
            regions = tuple(
                self._normalize_analyzed_region(
                    region,
                    tenant_id=tenant_id,
                    collection_id=collection_id,
                    document_id=document_id,
                    asset_id=asset_id,
                    page_number=page.page_number,
                    region_index=idx,
                )
                for idx, region in enumerate(raw_regions, start=1)
            )
            regions = _append_page_aggregate_regions(
                regions,
                tenant_id=tenant_id,
                collection_id=collection_id,
                document_id=document_id,
                asset_id=asset_id,
            )
            regions = self._materialize_crops(
                regions,
                raw_bytes=_page_image_bytes(page),
                content_type=str(page.metadata.get("page_image_content_type") or "image/png"),
                require_raw_bytes=True,
            )
            embedding_inputs = [
                f"{region.ocr_text}\n{region.generated_caption_text}".encode("utf-8")
                for region in regions
            ]
            if hasattr(self.visual_embedder, "policy_resolver"):
                raw_vectors = self.visual_embedder.embed(
                    embedding_inputs,
                    tenant_id=tenant_id,
                    collection_id=collection_id,
                    document_id=document_id,
                )
            else:
                raw_vectors = self.visual_embedder.embed(embedding_inputs)
            vectors = tuple(tuple(vec) for vec in raw_vectors)
            self._record_visual_cost(
                tenant_id,
                "visual_embedding_cost",
                collection_id=collection_id,
                job_id=job_id,
                trace_id=trace_id,
                quantity=len(vectors),
                unit="regions",
            )
            results.append(
                VisualIngestionResult(
                    asset=asset,
                    regions=regions,
                    visual_vectors=vectors,
                    caption_status="not_requested",
                )
            )
        return tuple(results)

    def _normalize_analyzed_region(
        self,
        region: LayoutRegion,
        *,
        tenant_id: str,
        collection_id: str,
        document_id: str,
        asset_id: str,
        page_number: int,
        region_index: int,
    ) -> LayoutRegion:
        bbox = region.bbox or BoundingBox(0.0, 0.0, 1.0, 1.0)
        ocr_text = self.redactor.redact_visual_text(region.ocr_text)
        caption = self.redactor.redact_visual_text(region.generated_caption_text)
        labels = tuple(
            sorted(
                {
                    label
                    for text in (region.ocr_text, region.generated_caption_text)
                    for label, _start, _end in self.redactor.classify(text)
                }
            )
        )
        return replace(
            region,
            tenant_id=tenant_id,
            collection_id=collection_id,
            document_id=document_id,
            asset_id=asset_id,
            region_id=f"{asset_id}:region:{region_index}",
            bbox=bbox,
            page_number=page_number,
            ocr_text=ocr_text,
            generated_caption_text=caption,
            metadata={
                **_visual_region_provenance_metadata(region),
                **_visual_region_redaction_metadata(region, ocr_labels=labels, caption_labels=()),
            },
        )

    def _materialize_crops(
        self,
        regions: tuple[LayoutRegion, ...],
        *,
        raw_bytes: bytes = b"",
        content_type: str = "image/png",
        require_raw_bytes: bool = False,
    ) -> tuple[LayoutRegion, ...]:
        if self.crops is None:
            return regions
        if require_raw_bytes and not raw_bytes:
            return regions
        materialized: list[LayoutRegion] = []
        for region in regions:
            crop = self.crops.create_region_crop(
                region,
                raw_bytes=raw_bytes,
                content_type=content_type,
            )
            materialized.append(
                replace(
                    region,
                    crop_uri=crop.crop_uri,
                    metadata={
                        **region.metadata,
                        "crop_id": crop.crop_id,
                        "crop_uri": crop.crop_uri,
                        "raw_crop_uri": str(crop.metadata.get("raw_crop_uri") or crop.crop_uri),
                        "redacted_crop_uri": str(crop.metadata.get("redacted_crop_uri") or ""),
                        "crop_content_type": str(
                            crop.metadata.get("crop_content_type") or content_type
                        ),
                    },
                )
            )
        return tuple(materialized)

    def _record_visual_cost(
        self,
        tenant_id: str,
        kind: str,
        *,
        collection_id: str,
        job_id: str,
        trace_id: str,
        quantity: int,
        unit: str,
    ) -> None:
        if not self.cost:
            return
        self.cost.record_visual_cost(
            tenant_id,
            kind=kind,
            amount=0.0,
            collection_id=collection_id,
            job_id=job_id,
            trace_id=trace_id,
            quantity=quantity,
            unit=unit,
            billable=False,
        )


def _sensitive_labels(redactor: Redactor, text: str) -> tuple[str, ...]:
    return tuple(sorted({label for label, _start, _end in redactor.classify(text)}))


def _page_image_bytes(page: object) -> bytes:
    metadata = getattr(page, "metadata", {}) or {}
    if not isinstance(metadata, dict):
        return b""
    raw = metadata.get("page_image_bytes")
    if isinstance(raw, bytes):
        return raw
    encoded = metadata.get("page_image_base64")
    if isinstance(encoded, str) and encoded:
        try:
            return base64.b64decode(encoded)
        except Exception:
            return b""
    return b""


def _append_page_aggregate_regions(
    regions: tuple[LayoutRegion, ...],
    *,
    tenant_id: str,
    collection_id: str,
    document_id: str,
    asset_id: str,
) -> tuple[LayoutRegion, ...]:
    """Add page-level OCR regions so multi-line visual claims can be verified as one crop."""

    if not regions:
        return regions
    grouped: dict[tuple[str, int], list[LayoutRegion]] = {}
    for region in regions:
        key = (str(region.asset_id or asset_id), int(region.page_number or 1))
        grouped.setdefault(key, []).append(region)

    aggregates: list[LayoutRegion] = []
    for (group_asset_id, page_number), page_regions in grouped.items():
        if len(page_regions) < 2:
            continue
        if any(
            region.region_type == "page" and region.metadata.get("page_aggregate")
            for region in page_regions
        ):
            continue
        page_text = "\n".join(
            region.ocr_text.strip() for region in page_regions if region.ocr_text.strip()
        )
        if not page_text:
            continue
        extraction_source = _first_metadata_value(
            page_regions, "extraction_source", "primary_evidence_source"
        )
        caption_source = _first_metadata_value(page_regions, "caption_source")
        caption = _first_region_value(page_regions, "generated_caption_text")
        confidence_values = [
            float(region.transcription_confidence)
            for region in page_regions
            if region.transcription_confidence is not None
        ]
        confidence = sum(confidence_values) / len(confidence_values) if confidence_values else None
        labels = sorted(
            {
                str(label)
                for region in page_regions
                for label in _metadata_labels(region.metadata.get("sensitive_detection_labels"))
            }
        )
        redaction_required = any(
            bool(region.metadata.get("visual_region_redaction_required")) for region in page_regions
        ) or bool(labels)
        metadata = {
            "page_aggregate": True,
            "aggregate_region_count": len(page_regions),
            "sensitive_detected": bool(labels),
            "sensitive_detection_labels": labels,
            "pii_redaction_applied": any(
                bool(region.metadata.get("pii_redaction_applied")) for region in page_regions
            ),
            "secret_redaction_applied": any(
                bool(region.metadata.get("secret_redaction_applied")) for region in page_regions
            ),
            "visual_region_redaction_required": redaction_required,
            "visual_region_redaction_status": (
                "required" if redaction_required else "not_required"
            ),
        }
        if extraction_source:
            metadata["extraction_source"] = extraction_source
            metadata["primary_evidence_source"] = extraction_source
        if caption_source:
            metadata["caption_source"] = caption_source
        if any(region.metadata.get("pdf_page_fallback") for region in page_regions):
            metadata["pdf_page_fallback"] = True
            metadata["pdf_page_fallback_reason"] = _first_metadata_value(
                page_regions, "pdf_page_fallback_reason"
            )
            metadata["source_pdf_ref"] = _first_metadata_value(page_regions, "source_pdf_ref")

        aggregates.append(
            LayoutRegion(
                tenant_id=tenant_id,
                collection_id=collection_id,
                document_id=document_id,
                asset_id=group_asset_id,
                region_id=f"{group_asset_id}:page:{page_number}",
                bbox=BoundingBox(0.0, 0.0, 1.0, 1.0),
                page_number=page_number,
                region_type="page",
                heading_path=("visual", "page"),
                ocr_text=page_text,
                generated_caption_text=caption,
                extraction_source=extraction_source,
                caption_source=caption_source,
                transcription_confidence=confidence,
                metadata=metadata,
            )
        )
    if not aggregates:
        return regions
    return (*regions, *aggregates)


def _first_metadata_value(regions: list[LayoutRegion], *keys: str) -> str:
    for region in regions:
        for key in keys:
            value = getattr(region, key, "") or region.metadata.get(key)
            if value:
                return str(value)
    return ""


def _first_region_value(regions: list[LayoutRegion], attr: str) -> str:
    for region in regions:
        value = getattr(region, attr, "")
        if value:
            return str(value)
    return ""


def _metadata_labels(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (list, tuple, set)):
        return tuple(str(item) for item in value)
    return ()


def _analysis_with_rendered_pdf_pages(
    analysis: DocumentAnalysis, raw_pdf: bytes
) -> DocumentAnalysis:
    missing_pages = [page.page_number for page in analysis.pages if not _page_image_bytes(page)]
    if not missing_pages:
        return analysis
    rendered = _render_pdf_pages(raw_pdf, missing_pages)
    if not rendered:
        return analysis
    pages = []
    for page in analysis.pages:
        image = rendered.get(page.page_number)
        if not image:
            pages.append(page)
            continue
        metadata = dict(page.metadata)
        metadata["page_image_bytes"] = image
        metadata["page_image_content_type"] = "image/png"
        pages.append(replace(page, metadata=metadata))
    return replace(analysis, pages=tuple(pages))


def _render_pdf_pages(raw_pdf: bytes, page_numbers: list[int]) -> dict[int, bytes]:
    if not raw_pdf or not page_numbers:
        return {}
    try:
        import pypdfium2 as pdfium  # type: ignore
    except Exception:  # pragma: no cover - optional production dependency
        return {}
    rendered: dict[int, bytes] = {}
    try:
        pdf = pdfium.PdfDocument(raw_pdf)
        for page_number in sorted(set(page_numbers)):
            page_index = page_number - 1
            if page_index < 0 or page_index >= len(pdf):
                continue
            page = pdf[page_index]
            bitmap = page.render(scale=2)
            image = bitmap.to_pil()
            output = BytesIO()
            image.save(output, format="PNG")
            rendered[page_number] = output.getvalue()
    except Exception:
        return rendered
    return rendered


def _render_all_pdf_pages(raw_pdf: bytes) -> dict[int, bytes]:
    if not raw_pdf:
        return {}
    try:
        import pypdfium2 as pdfium  # type: ignore
    except Exception:  # pragma: no cover - optional production dependency
        return {}
    rendered: dict[int, bytes] = {}
    try:
        pdf = pdfium.PdfDocument(raw_pdf)
        for page_index in range(len(pdf)):
            page = pdf[page_index]
            bitmap = page.render(scale=2)
            image = bitmap.to_pil()
            output = BytesIO()
            image.save(output, format="PNG")
            rendered[page_index + 1] = output.getvalue()
    except Exception:
        return rendered
    return rendered


def _with_pdf_page_number(
    result: VisualIngestionResult,
    *,
    page_number: int,
    document_ref: str,
    fallback_reason: str,
) -> VisualIngestionResult:
    asset_metadata = dict(result.asset.metadata)
    asset_metadata.update(
        {
            "source_pdf_ref": document_ref,
            "pdf_page_fallback": True,
            "pdf_page_fallback_reason": _safe_failure_code(fallback_reason),
        }
    )
    asset = replace(
        result.asset,
        storage_uri=document_ref,
        content_type="application/pdf-page",
        page_number=page_number,
        metadata=asset_metadata,
    )
    regions = tuple(
        replace(
            region,
            page_number=page_number,
            metadata={
                **region.metadata,
                "source_pdf_ref": document_ref,
                "pdf_page_fallback": True,
                "pdf_page_fallback_reason": _safe_failure_code(fallback_reason),
            },
        )
        for region in result.regions
    )
    return replace(result, asset=asset, regions=regions)


def _safe_failure_code(reason: str) -> str:
    lowered = (reason or "").lower()
    if "invalids3object" in lowered:
        return "textract_s3_object_unavailable"
    if "not configured" in lowered:
        return "async_analyzer_not_configured"
    if "access" in lowered or "permission" in lowered or "denied" in lowered:
        return "async_analyzer_access_denied"
    if not reason:
        return ""
    return "async_analyzer_failed"


def _failed_visual_document_result(
    *,
    document_id: str,
    raw: bytes,
    reason: str,
    parser_version: str,
    chunking_config_version: str,
) -> IngestionExecutionResult:
    return IngestionExecutionResult(
        status=JobStatus.FAILED.value,
        document_id=document_id,
        failure_reason=reason,
        content_checksum=hashlib.sha256(raw).hexdigest(),
        parser_version=parser_version,
        chunking_config_version=chunking_config_version,
    )


def _visual_region_provenance_metadata(region: LayoutRegion) -> dict:
    extraction_source = str(
        region.extraction_source or region.metadata.get("extraction_source") or ""
    )
    caption_source = str(region.caption_source or region.metadata.get("caption_source") or "")
    metadata: dict = {}
    if extraction_source:
        metadata["extraction_source"] = extraction_source
        metadata["primary_evidence_source"] = extraction_source
    if caption_source:
        metadata["caption_source"] = caption_source
    if region.transcription_confidence is not None:
        metadata["transcription_confidence"] = region.transcription_confidence
    return metadata


def _visual_region_redaction_metadata(
    region: LayoutRegion,
    *,
    ocr_labels: tuple[str, ...],
    caption_labels: tuple[str, ...],
) -> dict:
    labels = tuple(sorted(set(ocr_labels) | set(caption_labels)))
    sensitive_detected = bool(labels)
    metadata = dict(region.metadata)
    metadata.update(
        {
            "sensitive_detected": sensitive_detected,
            "sensitive_detection_labels": list(labels),
            "pii_redaction_applied": sensitive_detected,
            "secret_redaction_applied": "api_key" in labels,
            "pii_redaction_policy_ref": PII_REDACTION_POLICY_REF,
            "visual_region_redaction_required": sensitive_detected,
            "visual_region_redaction_status": "required" if sensitive_detected else "not_required",
            "visual_redaction_policy_ref": (
                VISUAL_REGION_REDACTION_REQUIRED_REF if sensitive_detected else "none"
            ),
        }
    )
    return metadata


class IngestionExecutor:
    """Reusable parse -> chunk -> embed -> upsert execution boundary.

    SQS workers and future Dagster assets should call this helper instead of growing parallel
    ingestion logic. The underlying ``IngestionService`` owns the actual atomic parse/chunk/embed/upsert
    operation for the active persistence adapter.
    """

    parser_version = "text-parser-v1"
    chunking_config_version = "sentence-chunker-v1"
    visual_parser_version = "visual-document-analysis-v1"
    visual_chunking_config_version = "visual-region-chunker-v1"

    def __init__(
        self,
        ingestion: IngestionService,
        *,
        visual_executor: VisualIngestionExecutor | None = None,
        async_document_analyzer: AsyncDocumentAnalyzer | None = None,
    ) -> None:
        self.ingestion = ingestion
        self.visual_executor = visual_executor or VisualIngestionExecutor(
            visual_embedder=HashingVisualEmbeddingProvider(dim=_embedding_dim(ingestion))
        )
        self.async_document_analyzer = async_document_analyzer

    def execute_document(
        self,
        *,
        tenant_id: str,
        collection_id: str,
        source_id: str,
        document_id: str,
        raw: bytes,
        content_type: str = "text/plain",
        document_ref: str = "",
        async_provider: str = "",
        async_job_id: str = "",
    ) -> IngestionExecutionResult:
        if _is_image_content_type(content_type):
            return self.execute_visual_image(
                tenant_id=tenant_id,
                collection_id=collection_id,
                source_id=source_id,
                document_id=document_id,
                raw=raw,
                content_type=content_type,
            )
        if _is_pdf_content_type(content_type):
            return self.execute_visual_document(
                tenant_id=tenant_id,
                collection_id=collection_id,
                source_id=source_id,
                document_id=document_id,
                raw=raw,
                content_type=content_type,
                document_ref=document_ref,
                async_provider=async_provider,
                async_job_id=async_job_id,
            )
        content_checksum = hashlib.sha256(raw).hexdigest()
        job = self.ingestion.ingest(
            tenant_id=tenant_id,
            collection_id=collection_id,
            source_id=source_id,
            document_id=document_id,
            raw=raw,
            content_type=content_type,
        )
        embedder = getattr(self.ingestion, "_embedder", None)
        return IngestionExecutionResult(
            status=job.status,
            document_id=job.document_id,
            chunk_count=job.chunk_count,
            failure_reason=job.failure_reason,
            skipped=job.skipped,
            content_checksum=content_checksum,
            parser_version=self.parser_version,
            chunking_config_version=self.chunking_config_version,
            embedding_model_version=getattr(embedder, "model_version", ""),
        )

    def execute_visual_image(
        self,
        *,
        tenant_id: str,
        collection_id: str,
        source_id: str,
        document_id: str,
        raw: bytes,
        content_type: str,
    ) -> IngestionExecutionResult:
        result = self.visual_executor.execute_image(
            tenant_id=tenant_id,
            collection_id=collection_id,
            source_id=source_id,
            document_id=document_id,
            image=raw,
            options=VisualIngestionOptions(content_type=content_type),
            job_id=f"visual:{document_id}",
        )
        chunk_count = self._persist_visual_results(
            tenant_id=tenant_id,
            collection_id=collection_id,
            source_id=source_id,
            document_id=document_id,
            checksum=hashlib.sha256(raw).hexdigest(),
            content_type=content_type,
            results=(result,),
        )
        return IngestionExecutionResult(
            status=JobStatus.SUCCEEDED.value,
            document_id=document_id,
            chunk_count=chunk_count,
            content_checksum=hashlib.sha256(raw).hexdigest(),
            parser_version=self.visual_parser_version,
            chunking_config_version=self.visual_chunking_config_version,
            embedding_model_version=result.asset.metadata.get("visual_embedding_model_version", ""),
        )

    def execute_visual_document(
        self,
        *,
        tenant_id: str,
        collection_id: str,
        source_id: str,
        document_id: str,
        raw: bytes,
        content_type: str,
        document_ref: str,
        async_provider: str = "",
        async_job_id: str = "",
    ) -> IngestionExecutionResult:
        if self.async_document_analyzer is None:
            fallback = self._execute_visual_pdf_page_fallback(
                tenant_id=tenant_id,
                collection_id=collection_id,
                source_id=source_id,
                document_id=document_id,
                raw=raw,
                content_type=content_type,
                document_ref=document_ref,
                failure_reason="visual async document analyzer is not configured",
            )
            if fallback is not None:
                return fallback
            return _failed_visual_document_result(
                document_id=document_id,
                raw=raw,
                reason="visual async document analyzer is not configured",
                parser_version=self.visual_parser_version,
                chunking_config_version=self.visual_chunking_config_version,
            )
        context = IngestContext(
            tenant_id=tenant_id,
            collection_id=collection_id,
            source_id=source_id,
            document_id=document_id,
            content_type=content_type,
        )
        try:
            if async_job_id:
                handle = JobHandle(
                    provider=async_provider
                    or str(getattr(self.async_document_analyzer, "provider_id", "")),
                    token=async_job_id,
                    document_ref=document_ref,
                    status=AsyncJobStatus.PENDING,
                )
            else:
                request = AsyncSubmitRequest(document_ref=document_ref, context=context)
                handle = self.async_document_analyzer.submit(request)
            analysis = self.async_document_analyzer.poll(handle)
        except Exception as exc:
            fallback = self._execute_visual_pdf_page_fallback(
                tenant_id=tenant_id,
                collection_id=collection_id,
                source_id=source_id,
                document_id=document_id,
                raw=raw,
                content_type=content_type,
                document_ref=document_ref,
                failure_reason=str(exc),
            )
            if fallback is not None:
                return fallback
            return _failed_visual_document_result(
                document_id=document_id,
                raw=raw,
                reason=str(exc),
                parser_version=self.visual_parser_version,
                chunking_config_version=self.visual_chunking_config_version,
            )
        if analysis.status in {AsyncJobStatus.PENDING, AsyncJobStatus.MORE_AVAILABLE}:
            return IngestionExecutionResult(
                status=JobStatus.RUNNING.value,
                document_id=document_id,
                content_checksum=hashlib.sha256(raw).hexdigest(),
                parser_version=self.visual_parser_version,
                chunking_config_version=self.visual_chunking_config_version,
                async_provider=analysis.provider or handle.provider,
                async_job_id=analysis.job_id or handle.token,
                async_job_status=analysis.status.value,
            )
        if analysis.status != AsyncJobStatus.SUCCEEDED:
            fallback = self._execute_visual_pdf_page_fallback(
                tenant_id=tenant_id,
                collection_id=collection_id,
                source_id=source_id,
                document_id=document_id,
                raw=raw,
                content_type=content_type,
                document_ref=document_ref,
                failure_reason=analysis.failure_reason
                or f"visual document analysis ended with {analysis.status.value}",
            )
            if fallback is not None:
                return fallback
            return IngestionExecutionResult(
                status=JobStatus.FAILED.value,
                document_id=document_id,
                failure_reason=analysis.failure_reason
                or f"visual document analysis ended with {analysis.status.value}",
                content_checksum=hashlib.sha256(raw).hexdigest(),
                parser_version=self.visual_parser_version,
                chunking_config_version=self.visual_chunking_config_version,
                async_provider=analysis.provider or handle.provider,
                async_job_id=analysis.job_id or handle.token,
                async_job_status=analysis.status.value,
            )
        analysis = _analysis_with_rendered_pdf_pages(analysis, raw)
        results = self.visual_executor.execute_document_analysis(
            tenant_id=tenant_id,
            collection_id=collection_id,
            source_id=source_id,
            document_id=document_id,
            document_ref=document_ref,
            analysis=analysis,
            job_id=analysis.job_id,
        )
        chunk_count = self._persist_visual_results(
            tenant_id=tenant_id,
            collection_id=collection_id,
            source_id=source_id,
            document_id=document_id,
            checksum=hashlib.sha256(raw).hexdigest(),
            content_type=content_type,
            results=results,
            async_provider=analysis.provider,
            async_job_id=analysis.job_id,
            async_job_status=analysis.status.value,
        )
        embedding_version = (
            results[0].asset.metadata.get("visual_embedding_model_version", "") if results else ""
        )
        return IngestionExecutionResult(
            status=JobStatus.SUCCEEDED.value,
            document_id=document_id,
            chunk_count=chunk_count,
            content_checksum=hashlib.sha256(raw).hexdigest(),
            parser_version=self.visual_parser_version,
            chunking_config_version=self.visual_chunking_config_version,
            embedding_model_version=embedding_version,
            async_provider=analysis.provider,
            async_job_id=analysis.job_id,
            async_job_status=analysis.status.value,
        )

    def _execute_visual_pdf_page_fallback(
        self,
        *,
        tenant_id: str,
        collection_id: str,
        source_id: str,
        document_id: str,
        raw: bytes,
        content_type: str,
        document_ref: str,
        failure_reason: str,
    ) -> IngestionExecutionResult | None:
        rendered = _render_all_pdf_pages(raw)
        if not rendered:
            return None
        results = tuple(
            _with_pdf_page_number(
                self.visual_executor.execute_image(
                    tenant_id=tenant_id,
                    collection_id=collection_id,
                    source_id=source_id,
                    document_id=document_id,
                    image=image,
                    options=VisualIngestionOptions(
                        captioning_enabled=True,
                        content_type="image/png",
                    ),
                    job_id=f"visual-pdf-page:{document_id}:{page_number}",
                ),
                page_number=page_number,
                document_ref=document_ref,
                fallback_reason=failure_reason,
            )
            for page_number, image in sorted(rendered.items())
        )
        if not any(result.regions for result in results):
            return None
        chunk_count = self._persist_visual_results(
            tenant_id=tenant_id,
            collection_id=collection_id,
            source_id=source_id,
            document_id=document_id,
            checksum=hashlib.sha256(raw).hexdigest(),
            content_type=content_type,
            results=results,
            async_provider="sync_page_image_fallback",
            async_job_status=AsyncJobStatus.SUCCEEDED.value,
        )
        embedding_version = (
            results[0].asset.metadata.get("visual_embedding_model_version", "") if results else ""
        )
        return IngestionExecutionResult(
            status=JobStatus.SUCCEEDED.value,
            document_id=document_id,
            chunk_count=chunk_count,
            content_checksum=hashlib.sha256(raw).hexdigest(),
            parser_version=self.visual_parser_version,
            chunking_config_version=self.visual_chunking_config_version,
            embedding_model_version=embedding_version,
            async_provider="sync_page_image_fallback",
            async_job_status=AsyncJobStatus.SUCCEEDED.value,
        )

    def _persist_visual_results(
        self,
        *,
        tenant_id: str,
        collection_id: str,
        source_id: str,
        document_id: str,
        checksum: str,
        content_type: str,
        results: tuple[VisualIngestionResult, ...],
        async_provider: str = "",
        async_job_id: str = "",
        async_job_status: str = "",
    ) -> int:
        from raku_rag.services.visual import visual_chunks_from_ingestion

        ocr_quality = _ocr_quality_metadata(results)
        quality_metadata = quality_metadata_from_ocr_metadata(ocr_quality)
        chunks = tuple(
            replace(chunk, metadata=with_quality_metadata(chunk.metadata, quality_metadata))
            for result in results
            for chunk in visual_chunks_from_ingestion(result)
        )
        vectors = tuple(vector for result in results for vector in result.visual_vectors)
        self.ingestion._store.purge(tenant_id, document_id)
        self.ingestion._store.upsert(list(zip(chunks, vectors)))
        existing = self.ingestion._registry.get(tenant_id, document_id)
        asset_ids = [result.asset.asset_id for result in results]
        first_asset = results[0].asset if results else None
        metadata = dict(existing.metadata) if existing else {}
        metadata.update(
            {
                "content_type": content_type,
                "visual_asset_ids": asset_ids,
                "visual_asset_storage_uri": first_asset.storage_uri if first_asset else "",
                "visual_asset_content_type": first_asset.content_type if first_asset else "",
                "caption_status": ",".join(result.caption_status for result in results),
                # ★V1 取込品質ゲート: aggregate the per-region Textract confidences the pipeline
                # already captures into a document-level verdict, so "ingested but unreadable"
                # scans are FLAGGED instead of silently answering from garbage OCR.
                **ocr_quality,
                **quality_metadata,
                "async_provider": async_provider,
                "async_job_id": async_job_id,
                "async_job_status": async_job_status,
            }
        )
        self.ingestion._registry.put(
            Document(
                tenant_id=tenant_id,
                collection_id=collection_id,
                document_id=document_id,
                source_id=source_id,
                version=(existing.version + 1) if existing else 1,
                checksum=checksum,
                metadata=metadata,
                created_at=existing.created_at if existing else _now(),
                updated_at=_now(),
                indexed_at=_now(),
                tombstone=False,
            )
        )
        return len(chunks)


class IngestionWorker:
    def __init__(
        self,
        *,
        queue: MessageQueue,
        connector: Connector,
        ingestion: IngestionService,
        runs: IngestionRunStore,
        executor: IngestionExecutor | None = None,
        source_sync_service: object | None = None,
    ) -> None:
        self.queue = queue
        self.connector = connector
        self.ingestion = ingestion
        self.executor = executor or IngestionExecutor(ingestion)
        self.runs = runs
        self.source_sync_service = source_sync_service
        self.stats = IngestionWorkerStats()

    def enqueue(self, message: IngestionJobMessage) -> IngestionRun:
        run, created = self.runs.create_queued(message)
        if created:
            message_id = self.queue.enqueue_message(message.to_dict())
            self.runs.mark_message_id(run, message_id)
        return run

    def process_once(self) -> bool:
        envelopes = self.queue.receive(max_messages=1)
        if not envelopes:
            return False
        envelope = envelopes[0]
        if envelope.body.get("job_type") == "source_sync":
            return self._process_source_sync(envelope)
        try:
            message = IngestionJobMessage.from_dict(envelope.body)
        except Exception as exc:
            self.queue.fail(envelope, str(exc))
            self.stats.failed += 1
            return True

        run, _ = self.runs.create_queued(message)
        if run.status == JobStatus.SUCCEEDED.value:
            self.queue.ack(envelope)
            self.stats.skipped_duplicates += 1
            return True

        self.runs.mark_message_id(run, envelope.message_id)
        self.runs.mark_running(run)
        try:
            raw = self.connector.fetch(message.document_ref)
            result = self.executor.execute_document(
                tenant_id=message.tenant_id,
                collection_id=message.collection_id,
                source_id=message.source_id,
                document_id=message.document_id,
                raw=raw,
                content_type=message.content_type,
                document_ref=message.document_ref,
                async_provider=run.async_provider,
                async_job_id=run.async_job_id,
            )
            if result.async_provider or result.async_job_id or result.async_job_status:
                self.runs.mark_async_job(
                    run,
                    provider=result.async_provider,
                    job_id=result.async_job_id,
                    status=result.async_job_status,
                )
            if result.status == JobStatus.SUCCEEDED.value:
                self.runs.mark_succeeded(
                    run,
                    chunk_count=result.chunk_count,
                    content_checksum=result.content_checksum,
                    parser_version=result.parser_version,
                    chunking_config_version=result.chunking_config_version,
                    embedding_model_version=result.embedding_model_version,
                )
                self._refresh_source_sync_parent(message)
                self.queue.ack(envelope)
                self.stats.processed += 1
            elif result.status == JobStatus.RUNNING.value:
                self._refresh_source_sync_parent(message)
                self._retry_later(
                    envelope,
                    reason=result.failure_reason or "visual document analysis is still running",
                )
            else:
                self._fail(
                    envelope, run, result.failure_reason or "ingestion failed", result=result
                )
                self._refresh_source_sync_parent(message)
        except Exception as exc:
            self._fail(envelope, run, str(exc))
            self._refresh_source_sync_parent(message)
        return True

    def _process_source_sync(self, envelope: QueueEnvelope) -> bool:
        if self.source_sync_service is None:
            self.queue.fail(envelope, "source sync service is not configured")
            self.stats.failed += 1
            return True
        try:
            message = SourceSyncJobMessage.from_dict(envelope.body)
        except Exception as exc:
            self.queue.fail(envelope, str(exc))
            self.stats.failed += 1
            return True
        try:
            execute = getattr(self.source_sync_service, "execute_source_sync")
            execute(message)
            self.queue.ack(envelope)
            self.stats.processed += 1
        except Exception as exc:
            moved_to_dlq = self.queue.fail(envelope, str(exc))
            self.stats.failed += 1
            if moved_to_dlq:
                self.stats.dead_lettered += 1
        return True

    def drain(self, *, max_messages: int = 100) -> IngestionWorkerStats:
        for _ in range(max_messages):
            if not self.process_once():
                break
        return self.stats

    def _fail(
        self,
        envelope: QueueEnvelope,
        run: IngestionRun,
        reason: str,
        *,
        result: IngestionExecutionResult | None = None,
    ) -> None:
        moved_to_dlq = self.queue.fail(envelope, reason)
        self.stats.failed += 1
        metadata = {
            "content_checksum": result.content_checksum if result else "",
            "parser_version": result.parser_version if result else "",
            "chunking_config_version": result.chunking_config_version if result else "",
            "embedding_model_version": result.embedding_model_version if result else "",
        }
        if moved_to_dlq:
            self.runs.mark_dead_letter(
                run, reason=reason, retry_count=envelope.receive_count, **metadata
            )
            self.stats.dead_lettered += 1
        else:
            self.runs.mark_failed(
                run, reason=reason, retry_count=envelope.receive_count, **metadata
            )

    def _retry_later(self, envelope: QueueEnvelope, *, reason: str) -> None:
        retry = getattr(self.queue, "retry_later", None)
        if callable(retry):
            retry(envelope, delay_seconds=ASYNC_ANALYSIS_RETRY_DELAY_SECONDS, reason=reason)
            return
        self.queue.fail(envelope, reason)

    def _refresh_source_sync_parent(self, message: IngestionJobMessage) -> None:
        parent_document_id = f"{message.source_id}::__source_sync__"
        if message.document_id == parent_document_id:
            return
        source_state = self.runs.source_sync_state(message.tenant_id, message.source_id)
        if source_state is None or not source_state.last_ingestion_run_id:
            return
        parent = self.runs.get_for_tenant(message.tenant_id, source_state.last_ingestion_run_id)
        if parent is None or parent.document_id != parent_document_id:
            return
        child_states = [
            state
            for state in self.runs.list_processing_states(
                message.tenant_id,
                collection_id=message.collection_id,
                source_id=message.source_id,
            )
            if state.document_id != parent_document_id
        ]
        observed = max(source_state.observed_count, len(child_states))
        changed = sum(1 for state in child_states if state.status == JobStatus.SUCCEEDED.value)
        failed = sum(
            1
            for state in child_states
            if state.status in {JobStatus.FAILED.value, JobStatus.DEAD_LETTER.value}
        )
        pending = observed - changed - failed
        chunk_count = sum(state.chunk_count for state in child_states)
        manifest_checksum = source_state.last_manifest_checksum
        if pending > 0:
            final_status = "syncing"
            self.runs.mark_running(parent)
            last_synced_at = ""
        elif observed > 0 and failed == observed:
            final_status = JobStatus.FAILED.value
            self.runs.mark_failed(parent, reason="all synced documents failed", retry_count=0)
            last_synced_at = ""
        elif failed:
            final_status = "partially_succeeded"
            self.runs.mark_partially_succeeded(
                parent,
                reason=f"{failed} synced document(s) failed",
                chunk_count=chunk_count,
                content_checksum=manifest_checksum,
            )
            last_synced_at = ""
        else:
            final_status = JobStatus.SUCCEEDED.value
            self.runs.mark_succeeded(
                parent,
                chunk_count=chunk_count,
                content_checksum=manifest_checksum,
            )
            last_synced_at = _now()
        self.runs.upsert_source_sync_state(
            SourceSyncState(
                tenant_id=source_state.tenant_id,
                source_id=source_state.source_id,
                collection_id=source_state.collection_id,
                status=final_status,
                last_manifest_checksum=manifest_checksum,
                last_ingestion_run_id=source_state.last_ingestion_run_id,
                observed_count=observed,
                changed_count=changed,
                deleted_count=source_state.deleted_count,
                skipped_count=source_state.skipped_count,
                failed_count=failed,
                last_synced_at=last_synced_at,
                created_at=source_state.created_at,
            )
        )


def _embedding_dim(ingestion: IngestionService) -> int:
    embedder = getattr(ingestion, "_embedder", None)
    return embedding_dimension(embedder) if embedder is not None else 32


def _is_image_content_type(content_type: str) -> bool:
    return content_type.lower().split(";", 1)[0].strip().startswith("image/")


def _is_pdf_content_type(content_type: str) -> bool:
    return content_type.lower().split(";", 1)[0].strip() == "application/pdf"
