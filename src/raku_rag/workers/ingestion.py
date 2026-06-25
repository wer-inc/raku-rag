"""Queue-driven ingestion worker.

This module wraps the existing 001 ``IngestionService`` with the production-track concerns that do
not belong in parse/chunk/embed itself: SQS-style messages, idempotency, run status projection, and
document processing state.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
import hashlib
from typing import Protocol

from raku_rag.domain.models import JobStatus, LayoutRegion, VisualAsset
from raku_rag.interfaces.base import Connector, Vector
from raku_rag.observability.redaction import Redactor
from raku_rag.providers.captioning import CaptioningResult, DeterministicCaptioningProvider
from raku_rag.providers.layout import DeterministicLayoutExtractor
from raku_rag.providers.ocr import DeterministicOcrEngine
from raku_rag.providers.task_queue import QueueEnvelope
from raku_rag.providers.visual_embeddings import HashingVisualEmbeddingProvider
from raku_rag.services.cost import CostService
from raku_rag.services.ingestion import IngestionService, PII_REDACTION_POLICY_REF

VISUAL_REGION_REDACTION_REQUIRED_REF = "visual-region-redaction-required"


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


@dataclass(frozen=True)
class VisualIngestionOptions:
    captioning_enabled: bool = True
    content_type: str = "image/png"


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
        ocr: DeterministicOcrEngine | None = None,
        layout: DeterministicLayoutExtractor | None = None,
        captioning: DeterministicCaptioningProvider | None = None,
        visual_embedder: HashingVisualEmbeddingProvider | None = None,
        redactor: Redactor | None = None,
        cost: CostService | None = None,
    ) -> None:
        self.ocr = ocr or DeterministicOcrEngine()
        self.layout = layout or DeterministicLayoutExtractor(self.ocr)
        self.captioning = captioning or DeterministicCaptioningProvider()
        self.visual_embedder = visual_embedder or HashingVisualEmbeddingProvider()
        self.redactor = redactor or Redactor()
        self.cost = cost

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

        raw_ocr_regions = self.ocr.extract(image)
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
            caption_result = self.captioning.caption(image)
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
                    replace(region, generated_caption_text=caption_result.generated_caption_text)
                    for region in regions
                )
        regions = tuple(
            replace(
                region,
                metadata=_visual_region_redaction_metadata(
                    region,
                    ocr_labels=ocr_sensitive_labels[idx] if idx < len(ocr_sensitive_labels) else (),
                    caption_labels=caption_result.sensitive_detection_labels,
                ),
            )
            for idx, region in enumerate(regions)
        )

        embedding_inputs = [
            f"{region.ocr_text}\n{region.generated_caption_text}".encode("utf-8")
            for region in regions
        ]
        vectors = tuple(tuple(vec) for vec in self.visual_embedder.embed(embedding_inputs))
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

    def __init__(self, ingestion: IngestionService) -> None:
        self.ingestion = ingestion

    def execute_document(
        self,
        *,
        tenant_id: str,
        collection_id: str,
        source_id: str,
        document_id: str,
        raw: bytes,
        content_type: str = "text/plain",
    ) -> IngestionExecutionResult:
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
                self.queue.ack(envelope)
                self.stats.processed += 1
            else:
                self._fail(
                    envelope, run, result.failure_reason or "ingestion failed", result=result
                )
        except Exception as exc:
            self._fail(envelope, run, str(exc))
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
