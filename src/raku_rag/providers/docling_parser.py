"""ADR-018 §9.1 — DoclingStructuredParser: Docling as the first-choice structured provider (Phase B4).

Docling is an OPT-IN heavy provider (§13.1): torch + layout/table models. This adapter imports it
lazily, so the Tier A gate and the default runtime never pull it in. When Docling is unavailable the
parser degrades to a deterministic offline fallback (text decode + a route_trace note) rather than
crashing — the same "heavy provider is optional in core, verified out-of-gate" pattern the project
uses for Bedrock / Textract / VLM.

Crucially (§P1) the output is normalized into our canonical ``ParsedDocument``; the raw
``DoclingDocument`` is provider output kept for reproducibility (§P2), never the record.
"""

from __future__ import annotations

import hashlib
import io
import json
import time
import math
import re
import unicodedata
from dataclasses import replace
from datetime import datetime, timezone

from raku_rag.domain.parsed_document import (
    ANCHOR_PAGE_BBOX,
    BLOCK_CAPTION,
    BLOCK_FOOTER,
    BLOCK_HEADER,
    BLOCK_HEADING,
    BLOCK_LIST_ITEM,
    BLOCK_PARAGRAPH,
    BLOCK_TABLE,
    BLOCK_TITLE,
    BLOCK_UNKNOWN,
    BLOCK_VISUAL_SUMMARY,
    Block,
    Figure,
    IngestionInfo,
    Page,
    ParsedDocument,
    Provenance,
    ProviderRun,
    QualityInfo,
    RouteTraceStep,
    SourceAnchor,
    Table,
    TableCell,
    TableColumn,
)
from raku_rag.providers.ocr.pluggable import OcrProvider, OcrResult, select_ocr_provider
from raku_rag.providers.page_routing import PAGE_CLEAN_DIGITAL, classify_page_route
from raku_rag.providers.vlm_draft import (
    VlmDraftProvider,
    VlmDraftResult,
    select_vlm_draft_provider,
)
from raku_rag.services.quality_detectors import (
    VisualArtifactDetector,
    VisualArtifactSignals,
    document_quality_dimensions,
    is_drawing_like,
    select_visual_artifact_detector,
    table_structure_confidence,
)
from raku_rag.services.provider_policy_runtime import provider_policy_allows

PROVIDER = "docling"

# Formats Docling is the first-choice structured parser for (§9.1). HTML is included so the adapter
# is verifiable without the (model-downloading) PDF pipeline.
DOCLING_CONTENT_TYPES = frozenset(
    {
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",  # pptx
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # docx
        "text/html",
        "image/png",
        "image/jpeg",
        "image/tiff",
    }
)

# §8.4 standalone-image uploads (写真・画像化された文書): these ARE single-page documents, so the
# visual-artifact detector (handwriting/seal/drawing) must run on them too, not just PDF pages.
_STANDALONE_IMAGE_CONTENT_TYPES = frozenset({"image/png", "image/jpeg", "image/tiff"})

# §6.2 page-level "digital_mojibake_suspicious" routing signal threshold (replacement-char ratio).
_PAGE_MOJIBAKE_RATIO = 0.02

# DoclingDocument DocItemLabel value -> our block kind (§7.5). Unknown labels fall back to unknown.
_LABEL_TO_KIND = {
    "title": BLOCK_TITLE,
    "section_header": BLOCK_HEADING,
    "text": BLOCK_PARAGRAPH,
    "paragraph": BLOCK_PARAGRAPH,
    "list_item": BLOCK_LIST_ITEM,
    "caption": BLOCK_CAPTION,
    "page_header": BLOCK_HEADER,
    "page_footer": BLOCK_FOOTER,
    "footnote": BLOCK_FOOTER,
    "code": BLOCK_PARAGRAPH,
    "formula": BLOCK_PARAGRAPH,
    "table": BLOCK_TABLE,
}


def docling_available() -> bool:
    """True iff the optional ``docling`` package can be imported."""
    import importlib.util

    return importlib.util.find_spec("docling") is not None


def _norm(text: str) -> str:
    return re.sub(r"[ \t]+", " ", unicodedata.normalize("NFKC", text or "")).strip()


def _bbox_tuple(prov) -> tuple[float, float, float, float] | None:
    """Extract [l, t, r, b] from a Docling ProvenanceItem, defensively across versions."""
    bbox = getattr(prov, "bbox", None)
    if bbox is None:
        return None
    try:
        return (float(bbox.l), float(bbox.t), float(bbox.r), float(bbox.b))
    except (AttributeError, TypeError, ValueError):
        return None


def _first_prov(item):
    provs = getattr(item, "prov", None) or ()
    return provs[0] if provs else None


class DoclingStructuredParser:
    """Structured parser backed by Docling (opt-in), normalizing to ``ParsedDocument`` (§P1)."""

    provider = PROVIDER

    def __init__(
        self,
        *,
        content_types: frozenset[str] = DOCLING_CONTENT_TYPES,
        ocr_provider: OcrProvider | None = None,
        vlm_provider: VlmDraftProvider | None = None,
        visual_artifact_detector: VisualArtifactDetector | None = None,
        expected_language: str = "",
        provider_policy_resolver: object | None = None,
    ) -> None:
        self._content_types = content_types
        self._converter = None  # lazy DocumentConverter (expensive to build)
        # §8.3 language_consistency dimension (opt-in per deployment, default "" => not computed).
        self._expected_language = expected_language
        # §4.2/§9.4: OCR is an INDEPENDENT provider, not Docling's built-in. Default is config-driven
        # (RAKU_OCR_PROVIDER, default "none") — never Docling's internal OCR.
        self._ocr = ocr_provider if ocr_provider is not None else select_ocr_provider()
        # §10/Phase D: VLM draft fallback for pages OCR can't read. Default NoOp; output is draft_visual.
        self._vlm = vlm_provider if vlm_provider is not None else select_vlm_draft_provider()
        # §8.4 handwriting/seal detection is a pluggable vision provider (default NoOp); drawing-like is
        # a stdlib heuristic computed unconditionally.
        self._visual_detector = (
            visual_artifact_detector
            if visual_artifact_detector is not None
            else select_visual_artifact_detector()
        )
        self._provider_policy_resolver = provider_policy_resolver

    def supports(self, content_type: str) -> bool:
        return content_type in self._content_types

    # --- converter ------------------------------------------------------------------------------
    def _get_converter(self):
        if self._converter is None:
            from docling.document_converter import DocumentConverter

            opts = self._format_options()
            self._converter = DocumentConverter(format_options=opts)
        return self._converter

    def _format_options(self):
        """PDF format options with Docling's built-in OCR DISABLED (§4.2) — structure only.

        Defensive/fail-closed: if the pipeline-options API differs across Docling versions, do not
        silently fall back to ``DocumentConverter()`` defaults. A default converter could re-enable
        Docling's built-in OCR, violating the ADR-018 provider split, so parse_structured catches the
        raised error and emits ``review_required`` / ``provider_error`` instead.
        """
        try:
            from docling.datamodel.base_models import InputFormat
            from docling.datamodel.pipeline_options import PdfPipelineOptions
            from docling.document_converter import PdfFormatOption

            opts = PdfPipelineOptions()
            opts.do_ocr = False  # Docling does layout/table structure, NOT OCR (§4.2/§9.4)
            opts.do_table_structure = True
            return {InputFormat.PDF: PdfFormatOption(pipeline_options=opts)}
        except Exception as exc:  # pragma: no cover - version drift
            raise RuntimeError("docling_ocr_disable_config_failed") from exc

    def _provider_version(self) -> str:
        try:
            from importlib.metadata import version

            return version("docling")
        except Exception:  # pragma: no cover - defensive
            return ""

    # --- entrypoint -----------------------------------------------------------------------------
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
    ) -> ParsedDocument:
        source = _source_info(raw, content_type, document_id=document_id, filename=filename)
        if not docling_available():
            return self._offline_fallback(raw, content_type, source)
        started_at = _utcnow()
        convert_started = time.perf_counter()
        try:
            result = self._convert(raw, content_type, filename=filename)
        except Exception as exc:  # extraction failure is a normal state (§P4), not a crash
            return self._extraction_error(raw, content_type, source, reason=str(exc)[:200])
        extract_latency_ms = (time.perf_counter() - convert_started) * 1000  # §18.3 Docling latency
        parsed = self._normalize(
            result.document,
            source,
            confidence=getattr(result, "confidence", None),
            started_at=started_at,
            finished_at=_utcnow(),
            extract_latency_ms=extract_latency_ms,
        )
        parsed = self._apply_preflight(parsed, raw, content_type)
        parsed = self._apply_visual_detectors(
            parsed,
            raw,
            content_type,
            tenant_id=tenant_id,
            collection_id=collection_id,
            document_id=document_id,
            provider_policy_id=provider_policy_id,
        )
        parsed = self._apply_external_ocr(
            parsed,
            raw,
            content_type,
            tenant_id=tenant_id,
            collection_id=collection_id,
            document_id=document_id,
            provider_policy_id=provider_policy_id,
        )
        parsed = _finalize_page_quality(parsed)
        return self._apply_quality_dimensions(parsed)

    def _apply_quality_dimensions(self, parsed: ParsedDocument) -> ParsedDocument:
        """§8.3: merge the derived dimension vector into the provider-confidence metrics."""
        derived = document_quality_dimensions(parsed, expected_language=self._expected_language)
        if not derived:
            return parsed
        metrics = {**dict(parsed.quality.metrics or {}), **derived}
        return replace(parsed, quality=replace(parsed.quality, metrics=metrics))

    # --- §8.4 visual detectors: drawing-like (stdlib heuristic) + handwriting/seal (pluggable) ------
    def _apply_visual_detectors(
        self,
        parsed: ParsedDocument,
        raw: bytes,
        content_type: str,
        *,
        tenant_id: str = "",
        collection_id: str = "",
        document_id: str = "",
        provider_policy_id: str = "default",
    ) -> ParsedDocument:
        if not parsed.pages:
            return parsed
        text_by_page: dict[int, str] = {}
        for block in parsed.blocks:
            if block.page_no:
                text_by_page[block.page_no] = text_by_page.get(block.page_no, "") + (
                    block.text or ""
                )
        figure_pages = {fig.page_no for fig in parsed.figures if fig.page_no}
        table_pages = {t.page_no for t in parsed.tables if t.page_no}
        detector = _PolicyGuardedVisualArtifactDetector(
            self._visual_detector,
            policy_resolver=self._provider_policy_resolver,
            tenant_id=tenant_id,
            collection_id=collection_id,
            document_id=document_id,
            provider_policy_id=provider_policy_id,
        )
        is_pdf = content_type == "application/pdf"
        is_standalone_image = content_type in _STANDALONE_IMAGE_CONTENT_TYPES
        detector_on = (is_pdf or is_standalone_image) and detector.available()
        # The per-page stdlib signals (drawing_like/table_heavy/mojibake_suspected) are always cheap to
        # compute; only the (potentially expensive) image render + vision-detector call is conditional.

        pages = []
        for page in parsed.pages:
            signals = dict(page.signals)
            page_text = text_by_page.get(page.page_no, "")
            if is_drawing_like(
                has_figures=page.page_no in figure_pages, text_char_count=len(page_text)
            ):
                signals["drawing_like"] = True
            # §6.2 routing signals the page-route table reads (table_heavy / digital-mojibake) —
            # otherwise PAGE_TABLE_HEAVY/PAGE_DIGITAL_MOJIBAKE could never be selected (page_routing.py).
            if page.page_no in table_pages:
                signals["table_heavy"] = True
            if page_text and (page_text.count("�") / len(page_text)) >= _PAGE_MOJIBAKE_RATIO:
                signals["mojibake_suspected"] = True
            if detector_on:
                image = (
                    render_pdf_page_png(raw, page.page_no)
                    if is_pdf
                    else _standalone_image_to_png(raw)
                )
                if image:
                    found = detector.detect(image, page_no=page.page_no)
                    if found.handwriting_detected:
                        signals["handwriting_detected"] = True
                    if found.seal_detected:
                        signals["seal_detected"] = True
                    if found.drawing_like:
                        signals["drawing_like"] = True
            pages.append(replace(page, signals=signals))
        return replace(parsed, pages=tuple(pages))

    # --- preflight (§6.1/§6.2): classify digital vs scanned pages, record routing signals ---------
    def _apply_preflight(
        self, parsed: ParsedDocument, raw: bytes, content_type: str
    ) -> ParsedDocument:
        if content_type != "application/pdf" or not parsed.pages:
            return parsed
        signals = preflight_pdf_pages(raw)
        if not signals:
            return parsed
        pages = tuple(
            replace(
                page,
                signals={**dict(page.signals), **signals.get(page.page_no, {})},
                page_type=(
                    "scanned"
                    if signals.get(page.page_no, {}).get("is_scanned")
                    else (page.page_type or "digital")
                ),
            )
            for page in parsed.pages
        )
        scanned = [no for no, s in signals.items() if s.get("is_scanned")]
        step = RouteTraceStep(
            stage="preflight",
            provider=PROVIDER,
            result=("scanned_pages" if scanned else "all_digital"),
            reason=f"scanned={scanned}" if scanned else "text_layer_present",
        )
        # §6.2: name the per-page route for any non-trivial page, so the routing decision is traceable
        # (§6.3). Execution of exotic routes stays opt-in on the providers; this records the intent.
        route_notes: list[str] = []
        for page in pages:
            route = classify_page_route(page.signals)
            if route.page_type != PAGE_CLEAN_DIGITAL:
                route_notes.append(f"p{page.page_no}:{route.page_type}->{route.primary}")
        new_steps: tuple[RouteTraceStep, ...] = (step,)
        if route_notes:
            new_steps += (
                RouteTraceStep(
                    stage="page_route",
                    provider=PROVIDER,
                    result=f"{len(route_notes)}_pages_routed",
                    reason="§6.2 per-page routing",
                    signals=tuple(route_notes[:32]),
                ),
            )
        return replace(parsed, pages=pages, route_trace=new_steps + parsed.route_trace)

    def _convert(self, raw: bytes, content_type: str, *, filename: str):
        from docling.datamodel.base_models import DocumentStream

        name = filename or f"upload{_ext_for(content_type)}"
        stream = DocumentStream(name=name, stream=io.BytesIO(raw))
        return self._get_converter().convert(stream)  # full ConversionResult (doc + confidence)

    def _config_hash(self) -> str:
        """Stable hash of the extraction config (§13.3) for reindex/regression/audit."""
        payload = json.dumps(
            {"do_ocr": False, "do_table_structure": True, "ocr_provider": self._ocr.name},
            sort_keys=True,
        )
        return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]

    # --- normalization: DoclingDocument -> ParsedDocument ---------------------------------------
    def _normalize(
        self,
        doc,
        source,
        *,
        confidence=None,
        started_at: str = "",
        finished_at: str = "",
        extract_latency_ms: float | None = None,
    ) -> ParsedDocument:
        version = self._provider_version()
        prov = Provenance(provider=PROVIDER, provider_version=version, route="docling_first")

        pages = _normalize_pages(doc)
        blocks, tables = _normalize_items(doc, prov)
        figures = _normalize_figures(doc, prov)  # A2 §7: capture pictures/figures
        quality = _quality_from_confidence(confidence)  # A3 §8.3: Docling confidence dimensions

        run = ProviderRun(
            provider=PROVIDER,
            provider_version=version,
            model_versions={
                # A5 §13.3: record the real docling package version behind each model role.
                "layout": f"docling-layout@{version}",
                "table": f"docling-tableformer@{version}",
                "ocr_provider": self._ocr.name,
            },
            config_hash=self._config_hash(),
            started_at=started_at,
            finished_at=finished_at,
            status="success",
        )
        route_trace = (
            # §4.2/§9.4: record that Docling's own OCR is OFF and which independent provider owns OCR.
            RouteTraceStep(
                stage="config",
                provider=PROVIDER,
                result="docling_ocr_disabled",
                reason=f"external_ocr={self._ocr.name}",
            ),
            RouteTraceStep(
                stage="extract",
                provider=PROVIDER,
                result="accepted",
                reason="docling",
                latency_ms=extract_latency_ms,
            ),
        )
        return ParsedDocument(
            source=source,
            ingestion=IngestionInfo(),
            provider_runs=(run,),
            pages=pages,
            blocks=blocks,
            tables=tables,
            figures=figures,
            quality=quality,
            route_trace=route_trace,
        )

    # --- external OCR (§4.2/§9.4): fill scanned/text-less pages via the independent provider -----
    def _apply_external_ocr(
        self,
        parsed: ParsedDocument,
        raw: bytes,
        content_type: str,
        *,
        tenant_id: str = "",
        collection_id: str = "",
        document_id: str = "",
        provider_policy_id: str = "default",
    ) -> ParsedDocument:
        if content_type != "application/pdf" or not parsed.pages:
            return parsed
        pages_with_text = {
            b.page_no for b in parsed.blocks if b.page_no is not None and b.embedding_text.strip()
        }
        empty_pages = [p.page_no for p in parsed.pages if p.page_no not in pages_with_text]
        if not empty_pages:
            return parsed

        extra_blocks, steps = apply_external_ocr(
            empty_pages,
            ocr_provider=_PolicyGuardedOcrProvider(
                self._ocr,
                policy_resolver=self._provider_policy_resolver,
                tenant_id=tenant_id,
                collection_id=collection_id,
                provider_policy_id=provider_policy_id,
            ),
            render=lambda page_no: render_pdf_page_png(raw, page_no),
            start_order=len(parsed.blocks),
            vlm_provider=_PolicyGuardedVlmDraftProvider(
                self._vlm,
                policy_resolver=self._provider_policy_resolver,
                tenant_id=tenant_id,
                collection_id=collection_id,
                provider_policy_id=provider_policy_id,
            ),
        )
        if not extra_blocks:
            return parsed
        return replace(
            parsed,
            blocks=parsed.blocks + tuple(extra_blocks),
            route_trace=parsed.route_trace + tuple(steps),
        )

    # --- degraded paths -------------------------------------------------------------------------
    def _offline_fallback(self, raw: bytes, content_type: str, source) -> ParsedDocument:
        return _text_fallback(
            raw,
            source,
            result="unavailable",
            reason="docling_not_installed",
            route="docling_unavailable_fallback",
        )

    def _extraction_error(self, raw: bytes, content_type: str, source, *, reason: str):
        return _text_fallback(
            raw, source, result="error", reason=reason, route="docling_error_fallback"
        )


class _PolicyGuardedOcrProvider:
    def __init__(
        self,
        inner: OcrProvider,
        *,
        policy_resolver: object | None,
        tenant_id: str,
        collection_id: str,
        provider_policy_id: str,
    ) -> None:
        self._inner = inner
        self._policy_resolver = policy_resolver
        self._tenant_id = tenant_id
        self._collection_id = collection_id
        self._provider_policy_id = provider_policy_id
        self.name = inner.name

    def available(self) -> bool:
        return self._inner.available() and provider_policy_allows(
            operation="ocr",
            provider=self.name,
            policy_resolver=self._policy_resolver,
            tenant_id=self._tenant_id,
            collection_id=self._collection_id,
            provider_policy_id=self._provider_policy_id,
        )

    def ocr_image(self, image_png: bytes) -> OcrResult:
        if not self.available():
            return OcrResult(provider=self.name)
        return self._inner.ocr_image(image_png)


class _PolicyGuardedVlmDraftProvider:
    def __init__(
        self,
        inner: VlmDraftProvider,
        *,
        policy_resolver: object | None,
        tenant_id: str,
        collection_id: str,
        provider_policy_id: str,
    ) -> None:
        self._inner = inner
        self._policy_resolver = policy_resolver
        self._tenant_id = tenant_id
        self._collection_id = collection_id
        self._provider_policy_id = provider_policy_id
        self.name = inner.name

    def available(self) -> bool:
        return self._inner.available() and provider_policy_allows(
            operation="vlm",
            provider=self.name,
            policy_resolver=self._policy_resolver,
            tenant_id=self._tenant_id,
            collection_id=self._collection_id,
            provider_policy_id=self._provider_policy_id,
        )

    def draft_from_image(self, image_png: bytes, *, page_no: int) -> VlmDraftResult:
        if not self.available():
            return VlmDraftResult(provider=self.name)
        return self._inner.draft_from_image(image_png, page_no=page_no)


class _PolicyGuardedVisualArtifactDetector:
    def __init__(
        self,
        inner: VisualArtifactDetector,
        *,
        policy_resolver: object | None,
        tenant_id: str,
        collection_id: str,
        document_id: str,
        provider_policy_id: str,
    ) -> None:
        self._inner = inner
        self._policy_resolver = policy_resolver
        self._tenant_id = tenant_id
        self._collection_id = collection_id
        self._document_id = document_id
        self._provider_policy_id = provider_policy_id
        self.name = inner.name

    def available(self) -> bool:
        return self._inner.available() and provider_policy_allows(
            operation="vlm",
            provider=self.name,
            policy_resolver=self._policy_resolver,
            tenant_id=self._tenant_id,
            collection_id=self._collection_id,
            provider_policy_id=self._provider_policy_id,
        )

    def detect(self, image_png: bytes, *, page_no: int) -> VisualArtifactSignals:
        if not self.available():
            return VisualArtifactSignals()
        return self._inner.detect(image_png, page_no=page_no)


# --- module helpers ------------------------------------------------------------------------------
def _source_info(raw: bytes, content_type: str, *, document_id: str, filename: str):
    from raku_rag.domain.parsed_document import SourceInfo

    return SourceInfo(
        document_id=document_id, filename=filename, mime_type=content_type, size_bytes=len(raw)
    )


def _ext_for(content_type: str) -> str:
    return {
        "application/pdf": ".pdf",
        "text/html": ".html",
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/tiff": ".tiff",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    }.get(content_type, ".bin")


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_figures(doc, prov) -> tuple[Figure, ...]:
    """Capture Docling pictures as Figure objects (A2 §7); empty when the document has none."""
    figures: list[Figure] = []
    for idx, pic in enumerate(getattr(doc, "pictures", ()) or ()):
        first = _first_prov(pic)
        caption = ""
        caption_fn = getattr(pic, "caption_text", None)
        if callable(caption_fn):
            try:
                caption = _norm(caption_fn(doc) or "")
            except Exception:  # pragma: no cover - caption API drift
                caption = ""
        figures.append(
            Figure(
                figure_id=f"fig_{idx}",
                page_no=getattr(first, "page_no", None),
                bbox=_bbox_tuple(first),
                caption=caption,
                provenance=prov,
            )
        )
    return tuple(figures)


def _quality_from_confidence(confidence) -> QualityInfo:
    """Map Docling's ConfidenceReport onto the §8.3 quality-dimension vector (A3).

    Records dimensions (never a single scalar, §8.2). Status stays informational/conservative here —
    hard thresholds are eval-driven (OQ#2); retrieval gating stays per-chunk in StructuredIngestion.
    """
    if confidence is None:
        return QualityInfo()
    mean = _score(getattr(confidence, "mean_score", None))
    low = _score(getattr(confidence, "low_score", None))
    layout = _score(getattr(confidence, "layout_score", None))
    metrics: dict[str, float] = {}
    if layout is not None:
        metrics["layout_confidence"] = layout
    if mean is not None:
        metrics["ocr_confidence_p50"] = mean
        metrics["overall"] = mean
    if low is not None:
        metrics["ocr_confidence_p10"] = low
    reasons: tuple[str, ...] = ()
    status = "accepted"
    if low is not None and low < 0.3:
        status, reasons = "accepted_with_warnings", ("low_confidence_regions",)
    return QualityInfo(status=status, reasons=reasons, metrics=metrics)


def _score(value) -> float | None:
    try:
        if value is None:
            return None
        f = float(value)
        if math.isnan(f) or math.isinf(
            f
        ):  # docling reports NaN for models that didn't run (e.g. HTML)
            return None
        return f
    except (TypeError, ValueError):
        return None


def _normalize_pages(doc) -> tuple[Page, ...]:
    pages_attr = getattr(doc, "pages", None)
    if not pages_attr:
        return ()
    out: list[Page] = []
    items = pages_attr.items() if hasattr(pages_attr, "items") else enumerate(pages_attr, start=1)
    for page_no, page in items:
        size = getattr(page, "size", None)
        width = int(getattr(size, "width", 0) or 0) if size else None
        height = int(getattr(size, "height", 0) or 0) if size else None
        out.append(Page(page_id=f"p_{page_no}", page_no=int(page_no), width=width, height=height))
    return tuple(out)


def _normalize_items(doc, prov) -> tuple[tuple[Block, ...], tuple[Table, ...]]:
    blocks: list[Block] = []
    tables: list[Table] = []
    order = 0

    iterate = getattr(doc, "iterate_items", None)
    if callable(iterate):
        for item, _level in iterate():
            block, table = _item_to_block(item, order, prov, doc)
            if block is not None:
                blocks.append(block)
                order += 1
            if table is not None:
                tables.append(table)
        return tuple(blocks), tuple(tables)

    # Fallback for older docling: texts + tables attributes.
    for item in getattr(doc, "texts", ()) or ():
        block, _ = _item_to_block(item, order, prov, doc)
        if block is not None:
            blocks.append(block)
            order += 1
    for item in getattr(doc, "tables", ()) or ():
        _, table = _item_to_block(item, order, prov, doc)
        if table is not None:
            tables.append(table)
    return tuple(blocks), tuple(tables)


def _label_value(item) -> str:
    label = getattr(item, "label", None)
    return str(getattr(label, "value", label) or "").lower()


def _item_to_block(item, order: int, prov, doc):
    label = _label_value(item)
    kind = _LABEL_TO_KIND.get(label, BLOCK_UNKNOWN)

    if kind == BLOCK_TABLE or hasattr(item, "data") and getattr(item, "data", None) is not None:
        table = _table_from_item(item, order, prov)
        if table is not None:
            first = _first_prov(item)
            block = Block(
                block_id=f"b_{order}",
                kind=BLOCK_TABLE,
                text=_table_text(item, doc),
                normalized_text=_table_text(item, doc),
                page_no=getattr(first, "page_no", None),
                bbox=_bbox_tuple(first),
                reading_order=order,
                source_anchor=_page_anchor(first),
                provenance=prov,
            )
            return block, table

    text = _norm(getattr(item, "text", "") or "")
    if not text:
        return None, None
    first = _first_prov(item)
    block = Block(
        block_id=f"b_{order}",
        kind=kind,
        text=text,
        normalized_text=text,
        page_no=getattr(first, "page_no", None),
        bbox=_bbox_tuple(first),
        reading_order=order,
        source_anchor=_page_anchor(first),
        provenance=prov,
    )
    return block, None


def _page_anchor(prov) -> SourceAnchor | None:
    if prov is None:
        return None
    page_no = getattr(prov, "page_no", None)
    bbox = _bbox_tuple(prov)
    if page_no is None and bbox is None:
        return None
    return SourceAnchor(type=ANCHOR_PAGE_BBOX, page_no=page_no, bbox=bbox)


_PAGE_QUALITY_RANK = {
    "accepted": 0,
    "accepted_with_warnings": 1,
    "review_required": 2,
    "draft_visual": 2,
    "rejected": 3,
}


def _finalize_page_quality(parsed: ParsedDocument) -> ParsedDocument:
    """§7.3 — give each Page its OWN quality verdict, not just the document-level aggregate.

    A page inherits the worst status among the blocks anchored to it (so a scanned page that fell back
    to a draft_visual/review_required block is reflected on the page itself); a page with no blocks of
    its own but a handwriting/seal/drawing-like signal (opt-in detectors) is flagged too. Purely
    additive — nothing reads Page.quality yet, so this cannot change existing behaviour.
    """

    if not parsed.pages:
        return parsed
    worst_by_page: dict[int, tuple[str, tuple[str, ...]]] = {}
    for block in parsed.blocks:
        if block.page_no is None:
            continue
        status = block.quality.status or "accepted"
        current = worst_by_page.get(block.page_no)
        if current is None or _PAGE_QUALITY_RANK.get(status, 0) > _PAGE_QUALITY_RANK.get(
            current[0], 0
        ):
            worst_by_page[block.page_no] = (status, tuple(block.quality.reasons))

    pages = []
    for page in parsed.pages:
        status, reasons = worst_by_page.get(page.page_no, ("accepted", ()))
        signals = dict(page.signals or {})
        if status == "accepted":
            if signals.get("handwriting_detected") or signals.get("seal_detected"):
                status, reasons = "review_required", ("handwriting_or_seal_detected",)
            elif signals.get("drawing_like"):
                status, reasons = "review_required", ("drawing_only_page",)
        pages.append(replace(page, quality=QualityInfo(status=status, reasons=reasons)))
    return replace(parsed, pages=tuple(pages))


def _table_text(item, doc) -> str:
    """A flat text rendering of a table for embedding (the structured cells stay in the Table)."""
    try:
        md = item.export_to_markdown(doc)
        if md:
            return _norm(md).replace(" | ", " | ")
    except Exception:
        pass
    return ""


def _cell_bbox(cell) -> tuple[float, float, float, float] | None:
    """Extract a docling TableCell's own bbox (not a ProvenanceItem's), defensively across versions."""
    bbox = getattr(cell, "bbox", None)
    if bbox is None:
        return None
    try:
        return (float(bbox.l), float(bbox.t), float(bbox.r), float(bbox.b))
    except (AttributeError, TypeError, ValueError):
        return None


def _table_from_item(item, order: int, prov) -> Table | None:
    data = getattr(item, "data", None)
    if data is None:
        return None
    columns: list[TableColumn] = []
    cells: list[TableCell] = []
    # §7.6 "行・列・ヘッダ・セル構造の信頼度" incl. merged cells (§3.3): ``table_cells`` is docling's
    # DEDUPLICATED logical-cell list (one entry per merged cell, with span info) — prefer it over the
    # dense ``grid`` (which repeats a merged cell's text at every grid position it occupies, so span
    # would be lost and the cell double-counted). Fall back to ``grid`` for older docling / fixtures.
    table_cells = getattr(data, "table_cells", None)
    if table_cells:
        for cell in table_cells:
            r_idx = int(getattr(cell, "start_row_offset_idx", 0)) + 1
            c_idx = int(getattr(cell, "start_col_offset_idx", 0)) + 1
            cell_text = _norm(getattr(cell, "text", "") or "")
            is_header = bool(
                getattr(cell, "column_header", False) or getattr(cell, "row_header", False)
            )
            rowspan = max(1, int(getattr(cell, "row_span", 1) or 1))
            colspan = max(1, int(getattr(cell, "col_span", 1) or 1))
            if is_header and r_idx == 1:
                columns.append(TableColumn(index=c_idx - 1, text=cell_text))
            cells.append(
                TableCell(
                    row=r_idx,
                    col=c_idx,
                    text=cell_text,
                    rowspan=rowspan,
                    colspan=colspan,
                    bbox=_cell_bbox(cell),
                    is_header=is_header,
                )
            )
    else:
        grid = getattr(data, "grid", None)
        if grid:
            for r_idx, row in enumerate(grid, start=1):
                for c_idx, cell in enumerate(row, start=1):
                    cell_text = _norm(getattr(cell, "text", "") or "")
                    is_header = bool(
                        getattr(cell, "column_header", False) or getattr(cell, "row_header", False)
                    )
                    if is_header and r_idx == 1:
                        columns.append(TableColumn(index=c_idx - 1, text=cell_text))
                    cells.append(
                        TableCell(row=r_idx, col=c_idx, text=cell_text, is_header=is_header)
                    )
    first = _first_prov(item)
    # §8.3/§8.4: record a table-structure confidence so a ragged/misdetected table can be gated.
    tsc = table_structure_confidence(cells)
    return Table(
        table_id=f"t_{order}",
        page_no=getattr(first, "page_no", None),
        bbox=_bbox_tuple(first),
        columns=tuple(columns),
        cells=tuple(cells),
        quality=QualityInfo(metrics={"table_structure_confidence": tsc}),
        provenance=prov,
    )


def preflight_pdf_pages(raw: bytes) -> dict[int, dict]:
    """ADR §6.1 preflight: per-page {has_text_layer, is_scanned} via the PDF text layer.

    A page with no extractable text layer is treated as scanned (image-only) — the signal that routes
    it to the external OCR provider (§6.2). Best-effort: returns {} if pypdfium2 is unavailable.
    """
    try:
        import pypdfium2 as pdfium

        out: dict[int, dict] = {}
        pdf = pdfium.PdfDocument(raw)
        try:
            for idx in range(len(pdf)):
                textpage = pdf[idx].get_textpage()
                try:
                    has_text = textpage.count_chars() > 0
                finally:
                    textpage.close()
                out[idx + 1] = {"has_text_layer": has_text, "is_scanned": not has_text}
        finally:
            pdf.close()
        return out
    except Exception:  # pragma: no cover - preflight is best-effort
        return {}


def _standalone_image_to_png(raw: bytes) -> bytes | None:
    """Normalize a standalone image upload (png/jpeg/tiff) to PNG bytes for the vision detector."""
    try:
        from PIL import Image

        img = Image.open(io.BytesIO(raw)).convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:  # pragma: no cover - best-effort, same pattern as render_pdf_page_png
        return None


def render_pdf_page_png(raw: bytes, page_no: int) -> bytes | None:
    """Render one PDF page (1-based) to PNG bytes for the OCR provider. None on any failure."""
    try:
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(raw)
        try:
            bitmap = pdf[page_no - 1].render(scale=2.0)
            buf = io.BytesIO()
            bitmap.to_pil().save(buf, format="PNG")
            return buf.getvalue()
        finally:
            pdf.close()
    except Exception:  # pragma: no cover - rendering is best-effort
        return None


def apply_external_ocr(empty_pages, *, ocr_provider, render, start_order: int, vlm_provider=None):
    """For each text-less page: external OCR -> VLM draft -> fail loud (§4.2/§9.4, §10, §P4).

    Returns (extra_blocks, route_trace_steps). Order of attempts per page:
    1) the INDEPENDENT OCR provider (accepted text);
    2) if OCR yields nothing and a VLM provider is available, a ``draft_visual`` block (§10 — never
       retrieval/high-risk eligible until a human approves it);
    3) otherwise a ``review_required`` block.
    Never leans on Docling's built-in OCR to paper over a scan.
    """
    extra_blocks: list[Block] = []
    steps: list[RouteTraceStep] = []
    order = start_order
    available = ocr_provider.available()
    vlm_available = bool(vlm_provider is not None and vlm_provider.available())

    for page_no in empty_pages:
        image = render(page_no) if (available or vlm_available) else None
        ocr_latency_ms: float | None = None
        result = None
        if available and image:
            ocr_started = time.perf_counter()
            result = ocr_provider.ocr_image(image)
            ocr_latency_ms = (time.perf_counter() - ocr_started) * 1000  # §18.3 OCR latency
        text = result.text.strip() if result else ""
        if not text and vlm_available and image:
            vlm_started = time.perf_counter()
            draft = vlm_provider.draft_from_image(image, page_no=page_no)
            vlm_latency_ms = (time.perf_counter() - vlm_started) * 1000  # §18.3 VLM latency
            draft_text = (draft.text or "").strip()
            if draft_text:
                extra_blocks.append(
                    Block(
                        block_id=f"vlm_{page_no}",
                        kind=BLOCK_VISUAL_SUMMARY,
                        text=draft_text,
                        normalized_text=draft_text,
                        page_no=page_no,
                        reading_order=order,
                        confidence=draft.confidence,
                        source_anchor=SourceAnchor(type=ANCHOR_PAGE_BBOX, page_no=page_no),
                        provenance=Provenance(
                            provider=draft.provider,
                            method="vlm_draft",
                            model_version=draft.model,
                            route="vlm_draft",
                            prompt_version=draft.prompt_version,
                            generation_config=draft.generation_config,
                        ),
                        quality=QualityInfo(
                            status="draft_visual", reasons=("vlm_output_unapproved",)
                        ),
                    )
                )
                steps.append(
                    RouteTraceStep(
                        stage="vlm",
                        provider=draft.provider,
                        result="draft_visual",
                        reason=f"page_{page_no}",
                        latency_ms=vlm_latency_ms,
                    )
                )
                order += 1
                continue
        if text:
            extra_blocks.append(
                Block(
                    block_id=f"ocr_{page_no}",
                    kind=BLOCK_PARAGRAPH,
                    text=text,
                    normalized_text=text,
                    page_no=page_no,
                    reading_order=order,
                    confidence=result.confidence,
                    source_anchor=SourceAnchor(type=ANCHOR_PAGE_BBOX, page_no=page_no),
                    provenance=Provenance(
                        provider=ocr_provider.name, method="external_ocr", route="external_ocr"
                    ),
                )
            )
            steps.append(
                RouteTraceStep(
                    stage="ocr",
                    provider=ocr_provider.name,
                    result="ocr_filled",
                    reason=f"page_{page_no}",
                    latency_ms=ocr_latency_ms,
                )
            )
        else:
            # Fail loud: no external OCR available/successful for a scanned page.
            extra_blocks.append(
                Block(
                    block_id=f"ocr_{page_no}",
                    kind=BLOCK_UNKNOWN,
                    text=f"[未OCR: page {page_no} — 外部OCR provider '{ocr_provider.name}' で読取不可]",
                    normalized_text="",
                    page_no=page_no,
                    reading_order=order,
                    source_anchor=SourceAnchor(type=ANCHOR_PAGE_BBOX, page_no=page_no),
                    provenance=Provenance(
                        provider=ocr_provider.name, method="external_ocr", route="external_ocr"
                    ),
                    quality=QualityInfo(
                        status="review_required", reasons=("scanned_no_external_ocr",)
                    ),
                )
            )
            steps.append(
                RouteTraceStep(
                    stage="ocr",
                    provider=ocr_provider.name,
                    result="review_required",
                    reason=f"page_{page_no}_no_external_ocr",
                )
            )
        order += 1
    return extra_blocks, steps


def _text_fallback(raw: bytes, source, *, result: str, reason: str, route: str) -> ParsedDocument:
    """Deterministic degraded output when Docling can't run — decode text, flag it in route_trace."""
    text = raw.decode("utf-8", errors="replace")
    text = re.sub(r"[ \t]+", " ", unicodedata.normalize("NFKC", text))
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    prov = Provenance(provider=PROVIDER, method="text_fallback", route=route)
    blocks = tuple(
        Block(
            block_id=f"b_{i}",
            kind=BLOCK_PARAGRAPH,
            text=para,
            normalized_text=para,
            reading_order=i,
            provenance=prov,
        )
        for i, para in enumerate(p for p in text.split("\n\n") if p.strip())
    )
    run = ProviderRun(provider=PROVIDER, status=result)
    route_trace = (
        RouteTraceStep(stage="extract", provider=PROVIDER, result=result, reason=reason),
    )
    # §8.4 "provider がすべて失敗" (§P4/§P5): the canonical parser could not run (unavailable) or raised
    # (error), so this is a raw byte-decode, not a real extraction — never let it read as "accepted".
    quality = QualityInfo(status="review_required", reasons=("provider_error",))
    return ParsedDocument(
        source=source,
        ingestion=IngestionInfo(),
        provider_runs=(run,),
        blocks=blocks,
        route_trace=route_trace,
        quality=quality,
    )
