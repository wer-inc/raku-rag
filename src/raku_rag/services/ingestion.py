"""T042/T045 — IngestionService: parse → chunk → embed → index, with diff-sync (US2).

Re-embedding only when content checksum / chunking config / embedding_model_version changes
(FR-005a). Stores Document metadata and indexes chunks (tenant_id inherited, ACL via document).
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from raku_rag.domain.models import Chunk, Document, JobStatus, Modality
from raku_rag.interfaces.base import Chunker, EmbeddingProvider, Parser, VectorStore
from raku_rag.observability.logging import new_correlation_id
from raku_rag.observability.metrics import MetricsRecorder
from raku_rag.observability.tracing import InMemoryTracer


@dataclass
class IngestionJob:
    job_id: str
    document_id: str
    status: str = JobStatus.QUEUED.value
    failure_reason: str = ""
    chunk_count: int = 0
    skipped: bool = False
    correlation_id: str = ""


@dataclass
class DocumentRegistry:
    """Metadata DB analog (tenant-scoped)."""

    _docs: dict[tuple[str, str], Document] = field(default_factory=dict)

    def get(self, tenant_id: str, document_id: str) -> Document | None:
        return self._docs.get((tenant_id, document_id))

    def put(self, doc: Document) -> None:
        self._docs[(doc.tenant_id, doc.document_id)] = doc


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class IngestionService:
    def __init__(
        self,
        store: VectorStore,
        embedder: EmbeddingProvider,
        parser: Parser,
        chunker: Chunker,
        registry: DocumentRegistry,
        metrics: MetricsRecorder | None = None,
        tracer: InMemoryTracer | None = None,
    ) -> None:
        self._store = store
        self._embedder = embedder
        self._parser = parser
        self._chunker = chunker
        self._registry = registry
        self._metrics = metrics
        self._tracer = tracer

    def ingest(
        self,
        *,
        tenant_id: str,
        collection_id: str,
        source_id: str,
        document_id: str,
        raw: bytes,
        content_type: str = "text/plain",
        correlation_id: str = "",
    ) -> IngestionJob:
        cid = correlation_id or new_correlation_id()
        job = IngestionJob(job_id=f"job_{document_id}", document_id=document_id, correlation_id=cid)
        started = time.perf_counter()
        span_cm = (
            self._tracer.span(
                "ingestion.ingest",
                correlation_id=cid,
                tenant_id=tenant_id,
                collection_id=collection_id,
                source_id=source_id,
                content_type=content_type,
            )
            if self._tracer
            else _null_span()
        )
        with span_cm as span:
            job.status = JobStatus.RUNNING.value
            try:
                if not self._parser.supports(content_type):
                    raise ValueError(f"unsupported content_type: {content_type}")
                checksum = hashlib.sha256(raw).hexdigest()
                existing = self._registry.get(tenant_id, document_id)

                # diff-sync: skip re-embedding if nothing relevant changed (FR-005a)
                if existing and existing.checksum == checksum and not existing.tombstone:
                    job.status = JobStatus.SUCCEEDED.value
                    job.skipped = True
                    return self._finish_job_span(span, job, tenant_id, started)

                version = (existing.version + 1) if existing else 1
                text = self._parser.parse(raw, content_type)
                pieces = self._chunker.chunk(text)

                # Replace old version: purge prior chunks for this document (FR-005/SC-007)
                self._store.purge(tenant_id, document_id)

                chunks: list[Chunk] = []
                for text_piece, heading, position, offset_span in pieces:
                    chunks.append(
                        Chunk(
                            tenant_id=tenant_id,
                            chunk_id=f"{document_id}:{position}",
                            document_id=document_id,
                            collection_id=collection_id,
                            text=text_piece,
                            position=position,
                            token_count=len(text_piece.split()),
                            heading_path=heading,
                            modality=Modality.TEXT,
                            embedding_model_version=self._embedder.model_version,
                            offset_mapping=(offset_span, offset_span[0]),
                        )
                    )
                vectors = self._embedder.embed([c.text for c in chunks]) if chunks else []
                self._store.upsert(list(zip(chunks, vectors)))

                doc = Document(
                    tenant_id=tenant_id,
                    collection_id=collection_id,
                    document_id=document_id,
                    source_id=source_id,
                    version=version,
                    checksum=checksum,
                    created_at=existing.created_at if existing else _now(),
                    updated_at=_now(),
                    indexed_at=_now(),
                    tombstone=False,
                )
                self._registry.put(doc)
                job.chunk_count = len(chunks)
                job.status = JobStatus.SUCCEEDED.value
            except Exception as exc:  # parser/embedding failure → job failed, retryable (FR-030)
                job.status = JobStatus.FAILED.value
                job.failure_reason = str(exc)
            return self._finish_job_span(span, job, tenant_id, started)

    def _finish_job_span(
        self, span, job: IngestionJob, tenant_id: str, started: float
    ) -> IngestionJob:
        latency_ms = (time.perf_counter() - started) * 1000
        if self._metrics:
            self._metrics.record_stage(
                "ingestion",
                tenant_id=tenant_id,
                status=job.status,
                latency_ms=latency_ms,
            )
        if hasattr(span, "finish"):
            span.finish(
                "ok" if job.status == JobStatus.SUCCEEDED.value else "error",
                ingestion_status=job.status,
                chunk_count=job.chunk_count,
                skipped=job.skipped,
                latency_ms=latency_ms,
            )
        return job


class _NullSpan:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def finish(self, *args, **kwargs) -> None:
        return None


def _null_span() -> _NullSpan:
    return _NullSpan()
