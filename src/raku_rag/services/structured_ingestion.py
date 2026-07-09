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
import os
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
    EXTRACTION_QUALITY_STATUS_KEY,
    RETRIEVAL_BLOCKING_QUALITY_STATUSES,
    QUALITY_STATUS_ACCEPTED,
    QUALITY_STATUS_ACCEPTED_WITH_WARNINGS,
    QUALITY_STATUS_REVIEW_REQUIRED,
    accepted_quality_metadata,
    accepted_with_warnings_quality_metadata,
    classify_text_extraction_quality,
    purge_quality_partitioned_document,
    review_required_quality_metadata,
    store_quality_partitioned_chunks,
)
from raku_rag.services.quality_detectors import is_language_mismatch
from raku_rag.services.quality_thresholds import quality_thresholds
from raku_rag.services.structured_chunking import StructuredChunk, chunk_parsed_document

PARSER_CONTRACT_VERSION = "v1"


class StructuredParser(Protocol):
    def supports(self, content_type: str) -> bool: ...

    def parse_structured(
        self,
        raw: bytes,
        content_type: str,
        *,
        document_id: str = "",
        filename: str = "",
        tenant_id: str = "",
        collection_id: str = "",
        provider_policy_id: str = "default",
    ) -> ParsedDocument: ...


RawSink = Callable[[str, dict], None]


# §8.4 document-level hard-fail thresholds over structured confidence signals. Conservative
# (false-accept-first, §P5); final thresholds are eval-driven (OQ#2).
_LOW_OVERALL_CONFIDENCE = 0.35
_LOW_LAYOUT_CONFIDENCE = 0.30
_LOW_TABLE_STRUCTURE_CONFIDENCE = 0.40


def classify_parsed_document_quality(
    parsed: ParsedDocument, *, expected_language: str = ""
) -> tuple[str, tuple[str, ...]]:
    """ADR §8.4 document-level gate using structured signals (Docling confidence + §8.4 detectors).

    Returns (status, reasons). ``review_required`` for: low overall/layout confidence; a table with
    low structure confidence; a page flagged handwriting/seal or drawing-only; or an expected-Japanese
    document whose extraction came out abnormally non-Japanese — conditions the text classifier can't
    see. (draft_visual pages keep their status via the per-block/chunk path, not here.)
    """

    thresholds = quality_thresholds()  # §OQ#2: env-tunable (RAKU_QT_*)
    metrics = dict(parsed.quality.metrics or {})
    reasons: list[str] = []
    status = parsed.quality.status or QUALITY_STATUS_ACCEPTED

    def _flag(reason: str) -> None:
        nonlocal status
        reasons.append(reason)
        status = QUALITY_STATUS_REVIEW_REQUIRED

    overall = metrics.get("overall")
    if overall is not None and overall < thresholds.low_overall_confidence:
        _flag("low_overall_confidence")
    layout = metrics.get("layout_confidence")
    if layout is not None and layout < thresholds.low_layout_confidence:
        _flag("low_layout_confidence")
    # §8.4 "OCR confidence 下位 percentile が低い" — the p10 dimension, not just the mean/overall.
    ocr_p10 = metrics.get("ocr_confidence_p10")
    if ocr_p10 is not None and ocr_p10 < thresholds.low_ocr_confidence_p10:
        _flag("low_ocr_confidence_p10")
    for table in parsed.tables:
        tsc = dict(table.quality.metrics or {}).get("table_structure_confidence")
        if tsc is not None and tsc < thresholds.low_table_structure_confidence:
            _flag("low_table_structure_confidence")
            break
    # §8.4 vision-detector signals recorded on pages (handwriting / seal / drawing-only).
    for page in parsed.pages:
        signals = dict(page.signals or {})
        if signals.get("handwriting_detected") or signals.get("seal_detected"):
            _flag("handwriting_or_seal_detected")
            break
    for page in parsed.pages:
        if dict(page.signals or {}).get("drawing_like"):
            _flag("drawing_only_page")
            break
    # §8.4 "非空ページなのに抽出テキストがほぼ空" at the document level (the per-chunk text classifier
    # can't see this — a chunk's own emptiness is circular). empty_page_risk is the fraction of pages
    # that have some layout content but yielded no text.
    empty_page_risk = metrics.get("empty_page_risk")
    if empty_page_risk is not None and empty_page_risk > thresholds.high_empty_page_risk:
        _flag("high_empty_page_risk")
    # §9.3 "表や段組の読み順が壊れていないか" — a high reading-order-inversion rate is a layout failure.
    reading_order_risk = metrics.get("reading_order_risk")
    if reading_order_risk is not None and reading_order_risk > thresholds.high_reading_order_risk:
        _flag("high_reading_order_risk")
    # §8.4 "provider がすべて失敗" — the route_trace recorded a hard provider error/exception.
    if metrics.get("provider_error"):
        _flag("provider_error")
    # §8.4 expected-ja-but-de-japanized (opt-in per source).
    if expected_language and is_language_mismatch(parsed.text_for_embedding(), expected_language):
        _flag("language_mismatch")
    return status, tuple(dict.fromkeys(reasons))


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
        expected_language: str = "",
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
        # §8.4 language-consistency: opt-in per source (default "" => no check).
        self._expected_language = expected_language

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

            provider_policy_id = str(
                (chunking_metadata or {}).get("provider_policy_id") or "default"
            )
            parsed = self._parser.parse_structured(
                raw,
                content_type,
                document_id=document_id,
                filename=filename,
                tenant_id=tenant_id,
                collection_id=collection_id,
                provider_policy_id=provider_policy_id,
            )
            if self._raw_sink is not None:
                self._raw_sink(document_id, parsed.to_dict())

            struct_chunks = chunk_parsed_document(parsed)
            doc_floor_status, doc_floor_reasons = classify_parsed_document_quality(
                parsed, expected_language=self._expected_language
            )
            parser_provider = parsed.provider_runs[0].provider if parsed.provider_runs else ""
            chunks = self._build_chunks(
                tenant_id,
                collection_id,
                document_id,
                struct_chunks,
                chunking_metadata,
                parsed=parsed,
                doc_floor_status=doc_floor_status,
                doc_floor_reasons=doc_floor_reasons,
                route_trace_meta={
                    **_route_trace_metadata(parsed),
                    **_page_route_metadata(parsed),
                    # §11.4 anchor-eligibility scoping: which parser produced this chunk (some, like
                    # text/docx, structurally have no page/bbox anchor concept — see is_high_risk_
                    # citation_quality_eligible).
                    "parser_provider": parser_provider,
                },
            )

            vectors = self._embedder.embed([c.text for c in chunks]) if chunks else []
            purge_quality_partitioned_document(self._store, tenant_id, document_id)
            _, quarantine_count = store_quality_partitioned_chunks(
                self._store, list(zip(chunks, vectors))
            )

            review_count = sum(
                1
                for c in chunks
                if c.metadata.get(EXTRACTION_QUALITY_STATUS_KEY)
                in RETRIEVAL_BLOCKING_QUALITY_STATUSES
            )
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
                    "parser_provider": parser_provider,
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
                    quarantined_chunk_count=quarantine_count,
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
        parsed: ParsedDocument,
        doc_floor_status: str = QUALITY_STATUS_ACCEPTED,
        doc_floor_reasons: tuple[str, ...] = (),
        route_trace_meta: Mapping[str, object] | None = None,
    ) -> list[Chunk]:
        pre_index = self._pii_redaction_mode == PII_REDACTION_PRE_INDEX
        chunks: list[Chunk] = []
        for position, sc in enumerate(struct_chunks):
            detected = self._redactor.classify(sc.text_for_embedding)
            labels = sorted({label for label, _s, _e in detected})
            redaction_applied = bool(detected) and pre_index
            text = (
                self._redactor.redact(sc.text_for_embedding)
                if redaction_applied
                else sc.text_for_embedding
            )

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
                **_provider_details_metadata(parsed, sc),
                **dict(route_trace_meta or {}),
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


def build_structured_parser(
    *, expected_language: str | None = None, provider_policy_resolver: object | None = None
) -> StructuredParser:
    """Compose the app's structured parser: Docling-first where ADR-018 requires it.

    PDF / DOCX / PPTX / images (and HTML, which Docling supports for lightweight verification) go to
    the opt-in DoclingStructuredParser first. Plain text / markdown remain the cheap text parser, and
    CSV / XLSX keep the existing spreadsheet parser so cell anchors remain byte-for-byte compatible.

    ``expected_language`` drives the §8.3 language_consistency gate (a JP deployment sets ``ja`` so
    a mostly-non-Japanese extraction routes to review). Deployments configure it with
    ``RAKU_EXPECTED_LANGUAGE``; unset keeps the gate off.
    """
    if expected_language is None:
        expected_language = os.environ.get("RAKU_EXPECTED_LANGUAGE", "")

    from raku_rag.providers.docling_parser import DoclingStructuredParser
    from raku_rag.providers.structured_parsers import (
        CompositeStructuredParser,
        DocxStructuredParser,
        SpreadsheetStructuredParser,
        TextStructuredParser,
    )

    return CompositeStructuredParser(
        (
            DoclingStructuredParser(
                expected_language=expected_language,
                provider_policy_resolver=provider_policy_resolver,
            ),
            TextStructuredParser(),
            SpreadsheetStructuredParser(),
            DocxStructuredParser(),
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
    provider_policy_resolver: object | None = None,
) -> StructuredIngestionService:
    """App factory (ADR-018 B5 wiring) — used behind the ``structured_ingest_enabled`` flag."""

    if raw_sink is None:
        from raku_rag.services.raw_sink import build_raw_sink

        raw_sink = build_raw_sink()  # §P2: fs/s3 via RAKU_RAW_SINK env; default None (no-op)

    # §8.4/§8.3 language-consistency: opt-in per deployment (default "" => no check/dimension).
    expected_language = os.environ.get("RAKU_EXPECTED_LANGUAGE", "")
    return StructuredIngestionService(
        store=store,
        embedder=embedder,
        structured_parser=structured_parser
        or build_structured_parser(
            expected_language=expected_language,
            provider_policy_resolver=provider_policy_resolver,
        ),
        registry=registry,
        metrics=metrics,
        tracer=tracer,
        pii_redaction_mode=pii_redaction_mode,
        raw_sink=raw_sink,
        expected_language=expected_language,
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
    if anchor.image_ref:
        meta["image_ref"] = anchor.image_ref
    return meta


def _route_trace_metadata(parsed: ParsedDocument) -> dict[str, object]:
    """§6.3 — persist the provider route_trace onto the chunk so review / debug / reprocess / customer
    explanation can see how the extraction was produced. Document-level and small (a few steps)."""

    steps = getattr(parsed, "route_trace", ()) or ()
    if not steps:
        return {}
    return {
        "route_trace": [
            {
                "stage": s.stage,
                "provider": s.provider,
                "result": s.result,
                "reason": s.reason,
                "signals": list(s.signals),
                "latency_ms": s.latency_ms,
            }
            for s in steps
        ]
    }


def _provider_details_metadata(parsed: ParsedDocument, chunk: StructuredChunk) -> dict[str, object]:
    """Persist provider/version/config context for reviewer/audit explanation (§12.1/§13.3)."""

    provider_details = []
    for run in getattr(parsed, "provider_runs", ()) or ():
        provider_details.append(
            {
                "provider": run.provider,
                "provider_version": run.provider_version,
                "model_versions": dict(run.model_versions or {}),
                "config_hash": run.config_hash,
                "status": run.status,
            }
        )

    source_ids = set(chunk.source_block_ids or ())
    block_details = []
    seen: set[tuple[object, ...]] = set()
    for block in getattr(parsed, "blocks", ()) or ():
        if source_ids and block.block_id not in source_ids:
            continue
        prov = getattr(block, "provenance", None)
        if prov is None:
            continue
        detail = {
            "block_id": block.block_id,
            "provider": prov.provider,
            "provider_version": prov.provider_version,
            "model_version": prov.model_version,
            "method": prov.method,
            "route": prov.route,
            "prompt_version": prov.prompt_version,
            "generation_config": dict(prov.generation_config or {}),
        }
        key = tuple(
            detail.get(k)
            for k in (
                "provider",
                "provider_version",
                "model_version",
                "method",
                "route",
                "prompt_version",
            )
        )
        if key in seen:
            continue
        seen.add(key)
        block_details.append(detail)

    result: dict[str, object] = {}
    if provider_details:
        result["provider_details"] = provider_details
    if block_details:
        result["block_provider_details"] = block_details
    return result


def _page_route_metadata(parsed: ParsedDocument) -> dict[str, object]:
    """§18.1/§18.2 — persist per-document page stats onto the chunk (document-level, deduped in stats):
    page_count, the §6.2 page_route_distribution, and separate per-artefact page counts (handwriting /
    seal / vertical-text / drawing), rather than only the combined §8.4 gate reason.
    """

    pages = getattr(parsed, "pages", ()) or ()
    if not pages:
        return {}
    from raku_rag.providers.page_routing import classify_page_route

    route_distribution: dict[str, int] = {}
    artefact_counts = {
        "handwriting_detected": 0,
        "seal_detected": 0,
        "vertical_text_suspected": 0,
        "drawing_like": 0,
    }
    for page in pages:
        signals = dict(getattr(page, "signals", None) or {})
        route = classify_page_route(signals)
        route_distribution[route.page_type] = route_distribution.get(route.page_type, 0) + 1
        for key in artefact_counts:
            if signals.get(key):
                artefact_counts[key] += 1
    return {
        "page_count": len(pages),
        "page_route_distribution": route_distribution,
        **{f"{key}_pages": count for key, count in artefact_counts.items()},
    }
