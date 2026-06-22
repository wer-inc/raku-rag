"""T042/T045 — IngestionService: parse → chunk → embed → index, with diff-sync (US2).

Re-embedding only when content checksum / chunking config / embedding_model_version changes
(FR-005a). Stores Document metadata and indexes chunks (tenant_id inherited, ACL via document).
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Mapping

from raku_rag.domain.models import Chunk, Document, JobStatus, Modality
from raku_rag.interfaces.base import Chunker, EmbeddingProvider, Parser, VectorStore
from raku_rag.observability.logging import new_correlation_id
from raku_rag.observability.metrics import MetricsRecorder
from raku_rag.observability.redaction import Redactor
from raku_rag.observability.tracing import InMemoryTracer
from raku_rag.providers.embeddings import embedding_dimension

PII_REDACTION_PRE_INDEX = "pre_index_redact"
PII_REDACTION_DETECT_ONLY = "detect_only"
PII_REDACTION_BLOCK = "block"
PII_REDACTION_MODES = {
    PII_REDACTION_PRE_INDEX,
    PII_REDACTION_DETECT_ONLY,
    PII_REDACTION_BLOCK,
}
PII_REDACTION_POLICY_REF = "default-regex-v1"


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

    def documents_for_tenant(self, tenant_id: str) -> tuple[Document, ...]:
        """All documents for a tenant — the public accessor (so callers don't reach into ``_docs``)."""
        return tuple(doc for (tid, _did), doc in self._docs.items() if tid == tenant_id)


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
        redactor: Redactor | None = None,
        pii_redaction_mode: str = PII_REDACTION_PRE_INDEX,
    ) -> None:
        self._store = store
        self._embedder = embedder
        self._parser = parser
        self._chunker = chunker
        self._registry = registry
        self._metrics = metrics
        self._tracer = tracer
        self._redactor = redactor or Redactor()
        self._pii_redaction_mode = _normalize_pii_redaction_mode(pii_redaction_mode)

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
        chunking_metadata: Mapping[str, object] | None = None,
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
                effective_chunking_metadata = _effective_chunking_metadata(
                    content_type=content_type,
                    existing_metadata=existing.metadata if existing else {},
                    chunking_metadata=chunking_metadata,
                )
                chunking_config = _chunking_config(self._chunker, effective_chunking_metadata)

                # diff-sync: skip re-embedding if nothing relevant changed (FR-005a)
                if (
                    existing
                    and existing.checksum == checksum
                    and not existing.tombstone
                    and existing.metadata.get("pii_redaction_mode", PII_REDACTION_PRE_INDEX)
                    == self._pii_redaction_mode
                    and existing.metadata.get("embedding_model_version", "")
                    == self._embedder.model_version
                    and int(existing.metadata.get("embedding_dimension") or 0)
                    == embedding_dimension(self._embedder)
                    and existing.metadata.get("chunking_config_version", "")
                    == chunking_config["chunking_config_version"]
                    and existing.metadata.get("chunking_profile", "")
                    == chunking_config["chunking_profile"]
                ):
                    job.status = JobStatus.SUCCEEDED.value
                    job.skipped = True
                    return self._finish_job_span(span, job, tenant_id, started)

                version = (existing.version + 1) if existing else 1
                text = self._parser.parse(raw, content_type)
                detected = self._redactor.classify(text)
                detection_labels = sorted({label for label, _start, _end in detected})
                sensitive_detected = bool(detected)
                if sensitive_detected and self._pii_redaction_mode == PII_REDACTION_BLOCK:
                    raise ValueError("sensitive content blocked by redaction policy")
                redaction_applied = (
                    sensitive_detected and self._pii_redaction_mode == PII_REDACTION_PRE_INDEX
                )
                indexed_text = self._redactor.redact(text) if redaction_applied else text
                pieces = _chunk_text(self._chunker, indexed_text, effective_chunking_metadata)

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
                            metadata={
                                "sensitive_detected": sensitive_detected,
                                "sensitive_detection_labels": detection_labels,
                                "pii_redaction_applied": redaction_applied,
                                "pii_redaction_mode": self._pii_redaction_mode,
                                "pii_redaction_policy_ref": PII_REDACTION_POLICY_REF,
                                "secret_redaction_applied": redaction_applied
                                and "api_key" in detection_labels,
                                "embedding_model_version": self._embedder.model_version,
                                "embedding_dimension": embedding_dimension(self._embedder),
                                **chunking_config,
                            },
                        )
                    )
                vectors = self._embedder.embed([c.text for c in chunks]) if chunks else []
                self._store.upsert(list(zip(chunks, vectors)))

                metadata = dict(existing.metadata) if existing else {}
                metadata.update(
                    {
                        "pii_redaction_applied": redaction_applied,
                        "pii_redaction_mode": self._pii_redaction_mode,
                        "pii_redaction_policy_ref": PII_REDACTION_POLICY_REF,
                        "secret_redaction_applied": redaction_applied
                        and "api_key" in detection_labels,
                        "sensitive_detected": sensitive_detected,
                        "sensitive_detection_labels": detection_labels,
                        "embedding_model_version": self._embedder.model_version,
                        "embedding_dimension": embedding_dimension(self._embedder),
                        **chunking_config,
                    }
                )
                doc = Document(
                    tenant_id=tenant_id,
                    collection_id=collection_id,
                    document_id=document_id,
                    source_id=source_id,
                    version=version,
                    checksum=checksum,
                    metadata=metadata,
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


def _normalize_pii_redaction_mode(mode: str) -> str:
    normalized = (mode or PII_REDACTION_PRE_INDEX).strip().lower().replace("-", "_")
    aliases = {
        "redact": PII_REDACTION_PRE_INDEX,
        "preindex_redact": PII_REDACTION_PRE_INDEX,
        "pre_index": PII_REDACTION_PRE_INDEX,
        "detect": PII_REDACTION_DETECT_ONLY,
        "tag_only": PII_REDACTION_DETECT_ONLY,
        "retain": PII_REDACTION_DETECT_ONLY,
        "fail": PII_REDACTION_BLOCK,
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in PII_REDACTION_MODES:
        raise ValueError(
            "unsupported pii_redaction_mode: "
            f"{mode!r}; expected one of {sorted(PII_REDACTION_MODES)}"
        )
    return normalized


def _effective_chunking_metadata(
    *,
    content_type: str,
    existing_metadata: Mapping[str, object],
    chunking_metadata: Mapping[str, object] | None,
) -> dict:
    effective = dict(existing_metadata)
    effective["content_type"] = content_type
    if chunking_metadata:
        effective.update(dict(chunking_metadata))
    return effective


def _chunking_config(chunker: Chunker, metadata: Mapping[str, object]) -> dict:
    if hasattr(chunker, "config_for_metadata"):
        return dict(chunker.config_for_metadata(metadata))  # type: ignore[attr-defined]
    return {
        "chunking_config_version": chunker.__class__.__name__,
        "chunking_profile": "default",
        "max_chunk_chars": 0,
        "chunk_overlap_chars": 0,
    }


def _chunk_text(
    chunker: Chunker, text: str, metadata: Mapping[str, object]
) -> list[tuple[str, tuple[str, ...], int, tuple[int, int]]]:
    if hasattr(chunker, "chunk_document"):
        return list(chunker.chunk_document(text, metadata=metadata))  # type: ignore[attr-defined]
    return chunker.chunk(text)


class _NullSpan:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def finish(self, *args, **kwargs) -> None:
        return None


def _null_span() -> _NullSpan:
    return _NullSpan()
