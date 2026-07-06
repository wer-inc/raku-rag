"""ADR-018 Phase B5 — StructuredIngestionService: parse via ParsedDocument, chunk structure-aware.

A SEPARATE, opt-in ingestion service that runs ALONGSIDE the legacy ``IngestionService`` (which is
untouched, so the live path carries no regression risk). It wires the Phase B pieces end to end:

    StructuredParser -> ParsedDocument (§7) -> structure-aware chunks (§11) -> quality gate (§8) ->
    embed -> index

Each chunk keeps its citation anchor (page+bbox or spreadsheet cell) and provenance, and inherits a
Phase A extraction-quality status so review_required content is quarantined out of retrieval exactly
as for the legacy path. The raw provider output (e.g. DoclingDocument) is handed to an optional
``raw_sink`` for reproducibility (§P2) — a blob store in production, a no-op by default.

stdlib only; the heavy Docling provider is injected (opt-in), never imported here.
"""

from __future__ import annotations

import hashlib
import time
from typing import Callable, Mapping, Protocol

from raku_rag.domain.models import Chunk, Document, JobStatus, Modality
from raku_rag.domain.parsed_document import ANCHOR_SPREADSHEET_CELL, ParsedDocument
from raku_rag.interfaces.base import EmbeddingProvider, VectorStore
from raku_rag.observability.logging import log, new_correlation_id
from raku_rag.observability.metrics import MetricsRecorder
from raku_rag.observability.redaction import Redactor
from raku_rag.observability.tracing import InMemoryTracer
from raku_rag.providers.embeddings import embedding_dimension
from raku_rag.services.ingestion import (
    PII_REDACTION_POLICY_REF,
    PII_REDACTION_PRE_INDEX,
    DocumentRegistry,
    IngestionJob,
    _normalize_pii_redaction_mode,
    _now,
)
from raku_rag.services.ingestion_quality import (
    EXTRACTION_QUALITY_REASONS_KEY,
    EXTRACTION_QUALITY_STATUS_KEY,
    RETRIEVAL_BLOCKING_QUALITY_STATUSES,
    QUALITY_STATUS_ACCEPTED,
    QUALITY_STATUS_ACCEPTED_WITH_WARNINGS,
    QUALITY_STATUS_REVIEW_REQUIRED,
    accepted_quality_metadata,
    accepted_with_warnings_quality_metadata,
    classify_text_extraction_quality,
    review_required_quality_metadata,
)
from raku_rag.services.structured_chunking import StructuredChunk, chunk_parsed_document

PARSER_CONTRACT_VERSION = "v1"


class StructuredParser(Protocol):
    def supports(self, content_type: str) -> bool: ...

    def parse_structured(
        self, raw: bytes, content_type: str, *, document_id: str = "", filename: str = ""
    ) -> ParsedDocument: ...


RawSink = Callable[[str, dict], None]


# §8.4 document-level hard-fail thresholds over structured confidence signals. Conservative
# (false-accept-first, §P5); final thresholds are eval-driven (OQ#2).
_LOW_OVERALL_CONFIDENCE = 0.35
_LOW_LAYOUT_CONFIDENCE = 0.30
_LOW_TABLE_STRUCTURE_CONFIDENCE = 0.40


def classify_parsed_document_quality(parsed: ParsedDocument) -> tuple[str, tuple[str, ...]]:
    """ADR §8.4 document-level gate using structured signals (Docling confidence + table structure).

    Returns (status, reasons). ``review_required`` when overall/layout confidence is below the floor,
    or a table is present with low structure confidence — conditions the text classifier can't see.
    """

    metrics = dict(parsed.quality.metrics or {})
    reasons: list[str] = []
    status = parsed.quality.status or QUALITY_STATUS_ACCEPTED

    overall = metrics.get("overall")
    if overall is not None and overall < _LOW_OVERALL_CONFIDENCE:
        reasons.append("low_overall_confidence")
        status = QUALITY_STATUS_REVIEW_REQUIRED
    layout = metrics.get("layout_confidence")
    if layout is not None and layout < _LOW_LAYOUT_CONFIDENCE:
        reasons.append("low_layout_confidence")
        status = QUALITY_STATUS_REVIEW_REQUIRED
    for table in parsed.tables:
        tsc = dict(table.quality.metrics or {}).get("table_structure_confidence")
        if tsc is not None and tsc < _LOW_TABLE_STRUCTURE_CONFIDENCE:
            reasons.append("low_table_structure_confidence")
            status = QUALITY_STATUS_REVIEW_REQUIRED
            break
    return status, tuple(reasons)


def _chunk_quality_metadata(
    chunk: StructuredChunk,
    *,
    doc_floor_status: str = QUALITY_STATUS_ACCEPTED,
    doc_floor_reasons: tuple[str, ...] = (),
) -> dict[str, object]:
    """Worst of: the document-level §8.4 floor, the block verdict, and the §8.4 text classifier."""

    if doc_floor_status in RETRIEVAL_BLOCKING_QUALITY_STATUSES:
        return review_required_quality_metadata(
            status=doc_floor_status, reasons=doc_floor_reasons or ("document_review_required",)
        )
    if chunk.quality_status in RETRIEVAL_BLOCKING_QUALITY_STATUSES:
        return review_required_quality_metadata(
            status=chunk.quality_status,
            reasons=chunk.quality_reasons or ("block_review_required",),
        )
    classified = classify_text_extraction_quality(
        chunk.text_for_embedding, raw_size=len(chunk.text_for_embedding.encode("utf-8"))
    )
    if classified[EXTRACTION_QUALITY_STATUS_KEY] in RETRIEVAL_BLOCKING_QUALITY_STATUSES:
        return classified
    if (
        chunk.quality_status == QUALITY_STATUS_ACCEPTED_WITH_WARNINGS
        or doc_floor_status == QUALITY_STATUS_ACCEPTED_WITH_WARNINGS
    ):
        return accepted_with_warnings_quality_metadata(
            reasons=chunk.quality_reasons or doc_floor_reasons
        )
    return classified


class StructuredIngestionService:
    def __init__(
        self,
        store: VectorStore,
        embedder: EmbeddingProvider,
        structured_parser: StructuredParser,
        registry: DocumentRegistry,
        metrics: MetricsRecorder | None = None,
        tracer: InMemoryTracer | None = None,
        redactor: Redactor | None = None,
        pii_redaction_mode: str = PII_REDACTION_PRE_INDEX,
        raw_sink: RawSink | None = None,
    ) -> None:
        self._store = store
        self._embedder = embedder
        self._parser = structured_parser
        self._registry = registry
        self._metrics = metrics
        self._tracer = tracer
        self._redactor = redactor or Redactor()
        self._pii_redaction_mode = _normalize_pii_redaction_mode(pii_redaction_mode)
        self._raw_sink = raw_sink

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
        filename: str = "",
    ) -> IngestionJob:
        cid = correlation_id or new_correlation_id()
        job = IngestionJob(job_id=f"job_{document_id}", document_id=document_id, correlation_id=cid)
        started = time.perf_counter()
        try:
            if not self._parser.supports(content_type):
                raise ValueError(f"unsupported content_type: {content_type}")
            job.status = JobStatus.RUNNING.value
            checksum = hashlib.sha256(raw).hexdigest()
            existing = self._registry.get(tenant_id, document_id)
            version = (existing.version + 1) if existing else 1

            parsed = self._parser.parse_structured(
                raw, content_type, document_id=document_id, filename=filename
            )
            if self._raw_sink is not None:
                self._raw_sink(document_id, parsed.to_dict())

            struct_chunks = chunk_parsed_document(parsed)
            doc_floor_status, doc_floor_reasons = classify_parsed_document_quality(parsed)
            chunks = self._build_chunks(
                tenant_id,
                collection_id,
                document_id,
                struct_chunks,
                chunking_metadata,
                doc_floor_status=doc_floor_status,
                doc_floor_reasons=doc_floor_reasons,
            )

            vectors = self._embedder.embed([c.text for c in chunks]) if chunks else []
            self._store.purge(tenant_id, document_id)
            self._store.upsert(list(zip(chunks, vectors)))

            review_count = sum(
                1
                for c in chunks
                if c.metadata.get(EXTRACTION_QUALITY_STATUS_KEY)
                in RETRIEVAL_BLOCKING_QUALITY_STATUSES
            )
            provider = parsed.provider_runs[0].provider if parsed.provider_runs else ""
            doc = Document(
                tenant_id=tenant_id,
                collection_id=collection_id,
                document_id=document_id,
                source_id=source_id,
                version=version,
                checksum=checksum,
                metadata={
                    **accepted_quality_metadata(),
                    **dict(chunking_metadata or {}),
                    "parser_contract_version": PARSER_CONTRACT_VERSION,
                    "parsed_document_schema_version": parsed.schema_version,
                    "parser_provider": provider,
                    "embedding_model_version": self._embedder.model_version,
                    "embedding_dimension": embedding_dimension(self._embedder),
                    "review_required_chunk_count": review_count,
                },
                created_at=existing.created_at if existing else _now(),
                updated_at=_now(),
                indexed_at=_now(),
                tombstone=False,
            )
            self._registry.put(doc)
            job.chunk_count = len(chunks)
            job.status = JobStatus.SUCCEEDED.value
            if review_count:
                log(
                    "structured_ingestion.quality_review_required",
                    correlation_id=cid,
                    tenant=tenant_id,
                    document_id=document_id,
                    review_required_chunk_count=review_count,
                )
                if self._metrics:
                    self._metrics.observe(
                        "structured_ingestion_review_required_chunk_count",
                        review_count,
                        labels={"tenant_id": tenant_id},
                    )
        except Exception as exc:  # parser/embedding failure => failed job (FR-030), retryable
            job.status = JobStatus.FAILED.value
            job.failure_reason = str(exc)
        finally:
            if self._metrics:
                # Reuse the canonical "ingestion" stage — this IS ingestion (a parallel parser path),
                # so it shares the dashboard's ingestion latency/status dimensions.
                self._metrics.record_stage(
                    "ingestion",
                    tenant_id=tenant_id,
                    status=job.status,
                    latency_ms=(time.perf_counter() - started) * 1000,
                )
        return job

    def _build_chunks(
        self,
        tenant_id: str,
        collection_id: str,
        document_id: str,
        struct_chunks: list[StructuredChunk],
        chunking_metadata: Mapping[str, object] | None,
        *,
        doc_floor_status: str = QUALITY_STATUS_ACCEPTED,
        doc_floor_reasons: tuple[str, ...] = (),
    ) -> list[Chunk]:
        pre_index = self._pii_redaction_mode == PII_REDACTION_PRE_INDEX
        chunks: list[Chunk] = []
        for position, sc in enumerate(struct_chunks):
            detected = self._redactor.classify(sc.text_for_embedding)
            labels = sorted({label for label, _s, _e in detected})
            redaction_applied = bool(detected) and pre_index
            text = self._redactor.redact(sc.text_for_embedding) if redaction_applied else sc.text_for_embedding

            metadata: dict[str, object] = {
                "sensitive_detected": bool(detected),
                "sensitive_detection_labels": labels,
                "pii_redaction_applied": redaction_applied,
                "pii_redaction_mode": self._pii_redaction_mode,
                "pii_redaction_policy_ref": PII_REDACTION_POLICY_REF,
                "embedding_model_version": self._embedder.model_version,
                "embedding_dimension": embedding_dimension(self._embedder),
                "parser_contract_version": PARSER_CONTRACT_VERSION,
                "parsed_chunk_kind": sc.kind,
                "source_block_ids": list(sc.source_block_ids),
                **_anchor_metadata(sc),
                **_chunk_quality_metadata(
                    sc, doc_floor_status=doc_floor_status, doc_floor_reasons=doc_floor_reasons
                ),
                **dict(chunking_metadata or {}),
            }
            chunks.append(
                Chunk(
                    tenant_id=tenant_id,
                    chunk_id=f"{document_id}:{position}",
                    document_id=document_id,
                    collection_id=collection_id,
                    text=text,
                    position=position,
                    token_count=len(text.split()),
                    heading_path=sc.heading_path,
                    modality=Modality.TEXT,
                    embedding_model_version=self._embedder.model_version,
                    offset_mapping=((0, len(text)), 0),
                    metadata=metadata,
                )
            )
        return chunks


def build_structured_parser() -> StructuredParser:
    """Compose the app's structured parser: existing parsers first (parity), Docling for the rest.

    Text / DOCX / CSV / XLSX / HTML keep the existing structured parsers (text_for_embedding parity
    with the legacy path); PDF / PPTX / images fall through to the opt-in DoclingStructuredParser
    (which itself owns OCR-provider selection per §4.2/§9.4 and degrades gracefully without docling).
    """

    from raku_rag.providers.docling_parser import DoclingStructuredParser
    from raku_rag.providers.structured_parsers import (
        CompositeStructuredParser,
        DocxStructuredParser,
        SpreadsheetStructuredParser,
        TextStructuredParser,
    )

    return CompositeStructuredParser(
        (
            TextStructuredParser(),
            DocxStructuredParser(),
            SpreadsheetStructuredParser(),
            DoclingStructuredParser(),
        )
    )


def build_structured_ingestion_service(
    *,
    store: VectorStore,
    embedder: EmbeddingProvider,
    registry: DocumentRegistry,
    metrics: MetricsRecorder | None = None,
    tracer: InMemoryTracer | None = None,
    pii_redaction_mode: str = PII_REDACTION_PRE_INDEX,
    structured_parser: StructuredParser | None = None,
    raw_sink: RawSink | None = None,
) -> StructuredIngestionService:
    """App factory (ADR-018 B5 wiring) — used behind the ``structured_ingest_enabled`` flag."""

    return StructuredIngestionService(
        store=store,
        embedder=embedder,
        structured_parser=structured_parser or build_structured_parser(),
        registry=registry,
        metrics=metrics,
        tracer=tracer,
        pii_redaction_mode=pii_redaction_mode,
        raw_sink=raw_sink,
    )


def _anchor_metadata(sc: StructuredChunk) -> dict[str, object]:
    """Surface the first citation anchor as flat metadata (page+bbox or spreadsheet cell)."""

    if not sc.source_anchors:
        return {}
    anchor = sc.source_anchors[0]
    if anchor.type == ANCHOR_SPREADSHEET_CELL:
        return {
            "anchor_type": anchor.type,
            "cell_sheet": anchor.sheet,
            "cell_row": anchor.row,
            "cell_col": anchor.col,
            "cell_header": anchor.header or "",
        }
    meta: dict[str, object] = {"anchor_type": anchor.type}
    if anchor.page_no is not None:
        meta["page_number"] = anchor.page_no
    if anchor.bbox is not None:
        meta["bbox"] = list(anchor.bbox)
    return meta
