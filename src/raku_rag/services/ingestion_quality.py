"""Extraction quality metadata and retrieval eligibility helpers.

The ingestion pipeline can add stronger parsers over time, but retrieval and answer generation need
one stable contract: chunks that still require extraction review must not become evidence.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from raku_rag.services.quality_thresholds import quality_thresholds

EXTRACTION_QUALITY_SCHEMA_VERSION = "ingestion_quality.v1"
EXTRACTION_QUALITY_SCHEMA_VERSION_KEY = "extraction_quality_schema_version"
EXTRACTION_QUALITY_STATUS_KEY = "extraction_quality_status"
EXTRACTION_QUALITY_REASONS_KEY = "extraction_quality_reasons"
RETRIEVAL_ELIGIBLE_KEY = "retrieval_eligible"
HIGH_RISK_CITATION_ELIGIBLE_KEY = "high_risk_citation_eligible"
QUALITY_REVIEW_REQUIRED_KEY = "quality_review_required"

QUALITY_STATUS_ACCEPTED = "accepted"
QUALITY_STATUS_ACCEPTED_WITH_WARNINGS = "accepted_with_warnings"
QUALITY_STATUS_REVIEW_REQUIRED = "review_required"
QUALITY_STATUS_REJECTED = "rejected"
QUALITY_STATUS_DRAFT_VISUAL = "draft_visual"
QUALITY_STATUS_MANUAL_APPROVED = "manual_approved"

RETRIEVAL_BLOCKING_QUALITY_STATUSES = frozenset(
    {
        QUALITY_STATUS_REVIEW_REQUIRED,
        QUALITY_STATUS_REJECTED,
        QUALITY_STATUS_DRAFT_VISUAL,
    }
)

_RETRIEVAL_ELIGIBLE_STATUSES = frozenset(
    {
        QUALITY_STATUS_ACCEPTED,
        QUALITY_STATUS_ACCEPTED_WITH_WARNINGS,
        QUALITY_STATUS_MANUAL_APPROVED,
    }
)

# Extractions that belong in the human review queue (ADR §12.1). draft_visual has no producer yet
# but is included so the queue projection is correct the moment Phase D starts emitting it.
_REVIEW_QUEUE_STATUSES = frozenset(
    {
        QUALITY_STATUS_REVIEW_REQUIRED,
        QUALITY_STATUS_DRAFT_VISUAL,
    }
)

# --- ADR §8.4 quality-reason codes ---------------------------------------------------------------
REASON_EMPTY_EXTRACTION = "empty_extraction"
REASON_CID_ARTIFACTS = "cid_artifacts"
REASON_MOJIBAKE_SUSPECTED = "mojibake_suspected"
REASON_MINOR_MOJIBAKE = "minor_mojibake"
REASON_LOW_OCR_CONFIDENCE = "low_ocr_confidence"

# Text-extraction quality bars. Phase A prioritises minimising *false accept* over automation rate
# (ADR §P5), so these deliberately fail toward review rather than silently accepting garbage text.
_EMPTY_YIELD_MIN_RAW_BYTES = 512
_MIN_TEXT_YIELD_CHARS = 1
_MOJIBAKE_HARD_RATIO = 0.02
_CONTROL_CHAR_HARD_RATIO = 0.05


def accepted_quality_metadata(
    *,
    status: str = QUALITY_STATUS_ACCEPTED,
    reasons: Sequence[str] = (),
    high_risk_citation_eligible: bool = True,
) -> dict[str, object]:
    """Metadata for parser output that is eligible to retrieve and cite."""

    return {
        EXTRACTION_QUALITY_SCHEMA_VERSION_KEY: EXTRACTION_QUALITY_SCHEMA_VERSION,
        EXTRACTION_QUALITY_STATUS_KEY: status,
        EXTRACTION_QUALITY_REASONS_KEY: tuple(str(reason) for reason in reasons if reason),
        RETRIEVAL_ELIGIBLE_KEY: True,
        HIGH_RISK_CITATION_ELIGIBLE_KEY: bool(high_risk_citation_eligible),
        QUALITY_REVIEW_REQUIRED_KEY: False,
    }


def review_required_quality_metadata(
    *,
    reasons: Sequence[str] = (),
    status: str = QUALITY_STATUS_REVIEW_REQUIRED,
) -> dict[str, object]:
    """Metadata for extracted content that must stay out of retrieval until reviewed."""

    return {
        EXTRACTION_QUALITY_SCHEMA_VERSION_KEY: EXTRACTION_QUALITY_SCHEMA_VERSION,
        EXTRACTION_QUALITY_STATUS_KEY: status,
        EXTRACTION_QUALITY_REASONS_KEY: tuple(str(reason) for reason in reasons if reason),
        RETRIEVAL_ELIGIBLE_KEY: False,
        HIGH_RISK_CITATION_ELIGIBLE_KEY: False,
        QUALITY_REVIEW_REQUIRED_KEY: True,
    }


def accepted_with_warnings_quality_metadata(
    *,
    reasons: Sequence[str] = (),
) -> dict[str, object]:
    """Metadata for content that is retrievable but not clean enough for high-risk citation.

    ADR §8.5 / §11.4: ``accepted_with_warnings`` stays in the primary index but is NOT a valid
    high-risk manufacturing citation unless a tenant policy explicitly allows it. Phase A takes the
    safe default (deny high-risk) — see [[chatbot-source-exposure-default-deny]].
    """

    return {
        EXTRACTION_QUALITY_SCHEMA_VERSION_KEY: EXTRACTION_QUALITY_SCHEMA_VERSION,
        EXTRACTION_QUALITY_STATUS_KEY: QUALITY_STATUS_ACCEPTED_WITH_WARNINGS,
        EXTRACTION_QUALITY_REASONS_KEY: tuple(str(reason) for reason in reasons if reason),
        RETRIEVAL_ELIGIBLE_KEY: True,
        HIGH_RISK_CITATION_ELIGIBLE_KEY: False,
        QUALITY_REVIEW_REQUIRED_KEY: False,
    }


def classify_text_extraction_quality(
    text: str | None,
    *,
    raw_size: int | None = None,
    content_type: str | None = None,
) -> dict[str, object]:
    """Map a text-extraction result onto the ADR §8.4 quality gate.

    Detects the failure modes reachable stdlib-only from an already-extracted string:

    * empty yield on a non-trivial input (non-empty bytes, ~empty text) => ``review_required``
    * broken-CMap / CID artefacts (``(cid:NNN)``) => ``review_required``
    * mojibake — U+FFFD or control-char density above the hard bar => ``review_required``
    * a trace of U+FFFD below the hard bar => ``accepted_with_warnings``

    Clean text stays ``accepted``. ``content_type`` is accepted for future format-specific tuning but
    the current signals are format-agnostic.
    """

    thresholds = quality_thresholds()  # §OQ#2: env-tunable (RAKU_QT_*), safety-first defaults
    body = text or ""
    stripped = body.strip()
    hard_reasons: list[str] = []
    soft_reasons: list[str] = []

    if (raw_size or 0) >= thresholds.empty_yield_min_raw_bytes and len(
        stripped
    ) < _MIN_TEXT_YIELD_CHARS:
        hard_reasons.append(REASON_EMPTY_EXTRACTION)

    if "(cid:" in body:
        hard_reasons.append(REASON_CID_ARTIFACTS)

    if body:
        replacement_ratio = body.count("�") / len(body)
        control_chars = sum(1 for ch in body if ord(ch) < 32 and ch not in "\t\n\r")
        control_ratio = control_chars / len(body)
        if (
            replacement_ratio >= thresholds.mojibake_hard_ratio
            or control_ratio >= thresholds.control_char_hard_ratio
        ):
            hard_reasons.append(REASON_MOJIBAKE_SUSPECTED)
        elif "�" in body:
            soft_reasons.append(REASON_MINOR_MOJIBAKE)

    if hard_reasons:
        return review_required_quality_metadata(reasons=tuple(hard_reasons))
    if soft_reasons:
        return accepted_with_warnings_quality_metadata(reasons=tuple(soft_reasons))
    return accepted_quality_metadata()


def quality_metadata_from_ocr_metadata(metadata: Mapping[str, object]) -> dict[str, object]:
    """Map existing OCR confidence metadata onto the common extraction-quality contract."""

    if bool(metadata.get("ocr_quality_review_required")):
        return review_required_quality_metadata(reasons=(REASON_LOW_OCR_CONFIDENCE,))
    return accepted_quality_metadata()


def with_quality_metadata(
    metadata: Mapping[str, object] | None,
    quality_metadata: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Merge quality metadata without dropping caller-owned fields."""

    merged = dict(metadata or {})
    quality = dict(quality_metadata or accepted_quality_metadata())
    merged.update(quality)
    return merged


def store_quality_partitioned_chunks(
    store: object, pairs: Sequence[tuple[object, object]]
) -> tuple[int, int]:
    """Write chunks to the primary index or quarantine store according to extraction quality.

    ADR-018 requires ``review_required`` / ``rejected`` / ``draft_visual`` output to stay out of the
    normal retrieval index. Stores that expose ``quarantine`` get a physical split; older stores fall
    back to the primary index so retrieval's quality filter remains a fail-closed backstop.
    """

    primary: list[tuple[object, object]] = []
    quarantined: list[tuple[object, object]] = []
    for chunk, vector in pairs:
        metadata = getattr(chunk, "metadata", None)
        status = extraction_review_status(metadata) or _quality_status(_metadata_mapping(metadata))
        if status in RETRIEVAL_BLOCKING_QUALITY_STATUSES:
            quarantined.append((chunk, vector))
        else:
            primary.append((chunk, vector))

    upsert = getattr(store, "upsert")
    if primary:
        upsert(primary)
    if quarantined:
        quarantine = getattr(store, "quarantine", None)
        if callable(quarantine):
            quarantine(quarantined)
        else:
            upsert(quarantined)
    return len(primary), len(quarantined)


def purge_quality_partitioned_document(store: object, tenant_id: str, document_id: str) -> int:
    """Purge a document from both the primary index and ADR-018 quarantine store."""

    removed = 0
    purge = getattr(store, "purge")
    removed += int(purge(tenant_id, document_id) or 0)
    purge_quarantine = getattr(store, "purge_quarantine", None)
    if callable(purge_quarantine):
        removed += int(purge_quarantine(tenant_id, document_id) or 0)
    return removed


def is_retrieval_eligible(metadata: Mapping[str, object] | object | None) -> bool:
    """Return whether parsed content is allowed into retrieval/answer evidence."""

    values = _metadata_mapping(metadata)
    if _is_explicit_false(values.get(RETRIEVAL_ELIGIBLE_KEY)):
        return False
    status = _quality_status(values)
    if status in RETRIEVAL_BLOCKING_QUALITY_STATUSES:
        return False
    if status and status not in _RETRIEVAL_ELIGIBLE_STATUSES:
        return False
    return True


_UNANCHORED_STRUCTURED_PROVIDERS = frozenset({"text_parser", "docx_parser"})


def is_high_risk_citation_quality_eligible(metadata: Mapping[str, object] | object | None) -> bool:
    """Return whether extraction quality allows a chunk to be high-risk manufacturing evidence."""

    values = _metadata_mapping(metadata)
    if not is_retrieval_eligible(values):
        return False
    if _is_explicit_false(values.get(HIGH_RISK_CITATION_ELIGIBLE_KEY)):
        return False
    # §11.4: "anchor がない chunk" / "provider・model・version trace がない chunk" are not high-risk
    # evidence-grade. Scoped to content produced by the ADR-018 structured pipeline (the presence of
    # ``parser_contract_version`` — set ONLY by structured_ingestion._build_chunks — is what tells us
    # this chunk is in-scope for the check); other pipelines' provenance conventions are untouched, so
    # this is additive and cannot regress pre-existing (pre-ADR-018) high-risk citations.
    if values.get("parser_contract_version"):
        has_trace = bool(values.get("embedding_model_version")) and bool(
            values.get("parsed_chunk_kind")
        )
        if not has_trace:
            return False
        # The anchor check only applies where an anchor mechanism actually exists. text_parser/
        # docx_parser (plain text/markdown/html/DOCX) have no page/bbox concept in this schema — a
        # clean DOCX/text chunk must not be permanently disqualified for lacking something it
        # structurally cannot produce. docling (page/bbox) and spreadsheet_parser (cell) chunks DO
        # have an anchor whenever extraction actually succeeded, so the check still applies to them.
        parser_provider = str(values.get("parser_provider") or "")
        if parser_provider not in _UNANCHORED_STRUCTURED_PROVIDERS:
            has_anchor = bool(values.get("anchor_type") or values.get("cell_sheet"))
            if not has_anchor:
                return False
    return True


def quality_exclusion_reason(metadata: Mapping[str, object] | object | None) -> str:
    values = _metadata_mapping(metadata)
    status = _quality_status(values)
    if status:
        return status
    if _is_explicit_false(values.get(RETRIEVAL_ELIGIBLE_KEY)):
        return "retrieval_ineligible"
    return ""


@dataclass(frozen=True)
class ExtractionReviewItem:
    """One quarantined extraction surfaced to the human review queue (ADR §12.1)."""

    tenant_id: str
    document_id: str
    chunk_id: str
    status: str
    reasons: tuple[str, ...]
    # §12.1 review-item context — enough for a reviewer to locate + judge the extraction. The page
    # image itself is fetched by the client from (document_id, page_no, bbox); route trace lives in the
    # ingestion run.
    page_no: int | None = None
    anchor_type: str = ""
    bbox: tuple[float, ...] | None = None
    text_snippet: str = ""
    suggested_action: str = ""
    route_trace: tuple[Mapping[str, object], ...] = ()
    provider_details: tuple[Mapping[str, object], ...] = ()
    block_provider_details: tuple[Mapping[str, object], ...] = ()


# §12.1 "suggested action" — reasons that flag a *provider* problem (garbled/empty/wrong OCR) suggest a
# reprocess with a different provider; visual artefacts go to a specialist; low-confidence structure is
# usually a quick human edit. Ordered by precedence.
_REPROCESS_REASONS = frozenset(
    {
        REASON_EMPTY_EXTRACTION,
        REASON_CID_ARTIFACTS,
        REASON_MOJIBAKE_SUSPECTED,
        REASON_LOW_OCR_CONFIDENCE,
        "language_mismatch",
    }
)
_ESCALATE_REASONS = frozenset({"drawing_only_page", "handwriting_or_seal_detected"})
_EDIT_REASONS = frozenset(
    {
        "low_overall_confidence",
        "low_layout_confidence",
        "low_table_structure_confidence",
        REASON_MINOR_MOJIBAKE,
    }
)


def _suggest_review_action(status: str, reasons: tuple[str, ...]) -> str:
    if status == QUALITY_STATUS_DRAFT_VISUAL:
        return "approve"  # reviewer verifies the crop, then approves/edits
    rset = set(reasons)
    if rset & _REPROCESS_REASONS:
        return "reprocess"
    if rset & _ESCALATE_REASONS:
        return "escalate"
    if rset & _EDIT_REASONS:
        return "edit_and_approve"
    return "review"


def extraction_review_status(metadata: Mapping[str, object] | object | None) -> str:
    """Return the quality status iff the extraction belongs in the review queue, else ``""``."""

    values = _metadata_mapping(metadata)
    status = _quality_status(values)
    if status in _REVIEW_QUEUE_STATUSES:
        return status
    if not status and bool(values.get(QUALITY_REVIEW_REQUIRED_KEY)):
        return QUALITY_STATUS_REVIEW_REQUIRED
    return ""


def extraction_review_items(
    items: Iterable[object],
    *,
    tenant_id: str | None = None,
) -> list[ExtractionReviewItem]:
    """Project stored chunks onto ADR §12.1 review-queue items.

    The SSOT is the stored quality metadata itself, so the queue can never drift from what retrieval
    actually excludes. ``items`` is an iterable of ``Chunk`` (or ``(Chunk, vector)`` pairs, as
    ``store.iter_items()`` yields). Only quarantined extractions (``review_required`` /
    ``draft_visual``) surface; accepted content is not a review item.
    """

    queue: list[ExtractionReviewItem] = []
    for item in items:
        chunk = item[0] if isinstance(item, tuple) else item
        if tenant_id is not None and getattr(chunk, "tenant_id", None) != tenant_id:
            continue
        metadata = getattr(chunk, "metadata", None)
        status = extraction_review_status(metadata)
        if not status:
            continue
        meta = _metadata_mapping(metadata)
        reasons = tuple(
            str(reason) for reason in (meta.get(EXTRACTION_QUALITY_REASONS_KEY) or ()) if reason
        )
        page_raw = meta.get("page_number")
        bbox_raw = meta.get("bbox")
        route_raw = meta.get("route_trace")
        provider_raw = meta.get("provider_details")
        block_provider_raw = meta.get("block_provider_details")
        text = str(getattr(chunk, "text", "") or "")
        queue.append(
            ExtractionReviewItem(
                tenant_id=str(getattr(chunk, "tenant_id", "") or ""),
                document_id=str(getattr(chunk, "document_id", "") or ""),
                chunk_id=str(getattr(chunk, "chunk_id", "") or ""),
                status=status,
                reasons=reasons,
                page_no=int(page_raw) if isinstance(page_raw, (int, float)) else None,
                anchor_type=str(meta.get("anchor_type") or ""),
                bbox=(
                    tuple(float(x) for x in bbox_raw)
                    if isinstance(bbox_raw, (list, tuple))
                    else None
                ),
                text_snippet=text[:240],
                suggested_action=_suggest_review_action(status, reasons),
                route_trace=(
                    tuple(dict(s) for s in route_raw if isinstance(s, Mapping))
                    if isinstance(route_raw, (list, tuple))
                    else ()
                ),
                provider_details=(
                    tuple(dict(s) for s in provider_raw if isinstance(s, Mapping))
                    if isinstance(provider_raw, (list, tuple))
                    else ()
                ),
                block_provider_details=(
                    tuple(dict(s) for s in block_provider_raw if isinstance(s, Mapping))
                    if isinstance(block_provider_raw, (list, tuple))
                    else ()
                ),
            )
        )
    return queue


def extraction_quality_stats(store: object, *, tenant_id: str | None = None) -> dict[str, object]:
    """ADR-018 §18 — ops snapshot of the extraction quality gate, from stored chunk metadata.

    Surfaces the §18.1 status distribution + per-status rates (accepted / accepted_with_warnings /
    review_required / rejected / draft_visual / manual_approved) and the §18.2 quality-reason counts
    (mojibake / empty_extraction / low_table_structure_confidence / drawing_only_page /
    handwriting_or_seal_detected / language_mismatch …), plus the §18.1 provider distribution
    (``by_provider``, the winning provider per chunk from the persisted route_trace) and ``fallback_rate``
    (how often a fallback provider was needed). Feeds monitoring/alerting — a rising quarantine or
    fallback rate flags an upstream extraction regression. Uses the ``iter_items`` scan; a Postgres
    GROUP BY variant is the scale version (future).
    """

    counts: dict[str, int] = {}
    by_reason: dict[str, int] = {}
    by_provider: dict[str, int] = {}  # §18.1 provider distribution (the winning provider per chunk)
    fallback_count = 0  # §18.1 fallback rate
    total = 0
    iter_items = getattr(store, "iter_all_items", None) or getattr(store, "iter_items", None)
    if callable(iter_items):
        for entry in iter_items():
            chunk = entry[0] if isinstance(entry, tuple) else entry
            if tenant_id is not None and getattr(chunk, "tenant_id", None) != tenant_id:
                continue
            values = _metadata_mapping(getattr(chunk, "metadata", None))
            status = _quality_status(values) or QUALITY_STATUS_ACCEPTED
            counts[status] = counts.get(status, 0) + 1
            for reason in values.get(EXTRACTION_QUALITY_REASONS_KEY) or ():
                if reason:
                    by_reason[str(reason)] = by_reason.get(str(reason), 0) + 1
            provider, had_fallback = _route_provider_and_fallback(values.get("route_trace"))
            if provider:
                by_provider[provider] = by_provider.get(provider, 0) + 1
            if had_fallback:
                fallback_count += 1
            total += 1
    quarantined = sum(counts.get(s, 0) for s in RETRIEVAL_BLOCKING_QUALITY_STATUSES)
    rates = {status: (count / total if total else 0.0) for status, count in counts.items()}
    return {
        "total": total,
        "by_status": counts,
        "rates": rates,
        "by_reason": by_reason,
        "by_provider": by_provider,
        "fallback_rate": (fallback_count / total) if total else 0.0,
        # §18.1 provider failure rate — a hard provider error/exception/unavailability (the
        # "provider_error" §8.4 gate reason), distinct from a fallback that still produced content.
        "provider_failure_rate": (by_reason.get("provider_error", 0) / total) if total else 0.0,
        "quarantined": quarantined,
        "quarantine_rate": (quarantined / total) if total else 0.0,
    }


def _percentile(values: list[float], p: float) -> float | None:
    """Linear-interpolation percentile (stdlib, no numpy). None on empty input."""

    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    k = (len(ordered) - 1) * (p / 100.0)
    lo = int(k)
    hi = min(lo + 1, len(ordered) - 1)
    if lo == hi:
        return ordered[lo]
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


def extraction_latency_cost_stats(
    store: object,
    *,
    tenant_id: str | None = None,
    cost_model: Mapping[str, float] | None = None,
) -> dict[str, object]:
    """ADR-018 §18.3 — latency (measured) + cost (config) from the persisted route_trace.

    route_trace is document-level, so this dedupes by document_id (each document's trace counted once)
    to avoid multiplying by chunk count. Reports per-stage latency p50/p95 (Docling ``extract`` / ``ocr``
    / ``vlm``), per-provider call counts, and cost from the ``RAKU_INGEST_COST_MODEL`` cost map (0 when
    unconfigured — honest rather than invented). Feeds the §18.3 dashboard.
    """

    if cost_model is None:
        from raku_rag.services.ingestion_cost import provider_cost_model

        cost_model = provider_cost_model()

    seen_docs: set[str] = set()
    latency_by_stage: dict[str, list[float]] = {}
    provider_calls: dict[str, int] = {}
    cost_by_provider: dict[str, float] = {}
    total_cost = 0.0
    pages_processed = 0
    route_distribution: dict[str, int] = {}
    artefact_pages = {
        "handwriting_detected_pages": 0,
        "seal_detected_pages": 0,
        "vertical_text_suspected_pages": 0,
        "drawing_like_pages": 0,
    }

    iter_items = getattr(store, "iter_all_items", None) or getattr(store, "iter_items", None)
    if callable(iter_items):
        for entry in iter_items():
            chunk = entry[0] if isinstance(entry, tuple) else entry
            if tenant_id is not None and getattr(chunk, "tenant_id", None) != tenant_id:
                continue
            doc_id = str(getattr(chunk, "document_id", "") or "")
            if doc_id in seen_docs:
                continue  # this document's page/route stats are document-level — count once
            seen_docs.add(doc_id)
            values = _metadata_mapping(getattr(chunk, "metadata", None))
            # §18.1 pages processed + §6.2 route distribution (document-level, from _page_route_metadata).
            page_count = values.get("page_count")
            if isinstance(page_count, (int, float)):
                pages_processed += int(page_count)
            for page_type, count in (values.get("page_route_distribution") or {}).items():
                if isinstance(count, (int, float)):
                    route_distribution[str(page_type)] = route_distribution.get(
                        str(page_type), 0
                    ) + int(count)
            for key in artefact_pages:
                count = values.get(key)
                if isinstance(count, (int, float)):
                    artefact_pages[key] += int(count)
            route = values.get("route_trace")
            if not isinstance(route, (list, tuple)):
                continue
            for step in route:
                step_map = step if isinstance(step, Mapping) else {}
                stage = str(step_map.get("stage") or "")
                provider = str(step_map.get("provider") or "")
                latency = step_map.get("latency_ms")
                if isinstance(latency, (int, float)):
                    latency_by_stage.setdefault(stage, []).append(float(latency))
                if provider and stage in {"extract", "ocr", "vlm"}:
                    provider_calls[provider] = provider_calls.get(provider, 0) + 1
                    unit = float(cost_model.get(provider, 0.0) or 0.0)
                    cost_by_provider[provider] = cost_by_provider.get(provider, 0.0) + unit
                    total_cost += unit

    docs = len(seen_docs)
    latency = {
        stage: {"p50": _percentile(vals, 50), "p95": _percentile(vals, 95), "count": len(vals)}
        for stage, vals in latency_by_stage.items()
    }
    return {
        "documents": docs,
        "pages_processed": pages_processed,
        "route_distribution": route_distribution,
        **artefact_pages,
        "cost_per_page": (total_cost / pages_processed) if pages_processed else 0.0,
        "latency_ms_by_stage": latency,
        "provider_calls": provider_calls,
        "cost_by_provider": cost_by_provider,
        "total_cost": total_cost,
        "cost_per_document": (total_cost / docs) if docs else 0.0,
    }


_REVIEW_ACTION_PREFIX = "extraction_review."
# A definitive reversal of the accept/reject decision — the only overturn that needs no interpretation
# of intent (an escalate/reprocess in between doesn't itself count; it's the accept<->reject flip).
_OVERTURN_PAIR = frozenset({QUALITY_STATUS_MANUAL_APPROVED, QUALITY_STATUS_REJECTED})


def review_overturn_stats(
    events: Iterable[object], *, tenant_id: str | None = None
) -> dict[str, object]:
    """ADR-018 §18.2 — review overturn rate: chunks whose review history was reversed.

    Reads audit events (``AuditSink.events()``-shaped: ``.action``, ``.decision``, ``.chunk_ids`` or
    ``.resource_id``, ``.tenant_id``) for ``extraction_review.*`` actions, groups them by chunk, and
    flags a chunk as "overturned" when its history contains BOTH manual_approved and rejected at
    different points — a reviewer's accept/reject verdict was later reversed by another review action.
    """

    by_chunk: dict[str, list[str]] = {}
    for event in events:
        if tenant_id is not None and str(getattr(event, "tenant_id", "") or "") != tenant_id:
            continue
        action = str(getattr(event, "action", "") or "")
        if not action.startswith(_REVIEW_ACTION_PREFIX):
            continue
        chunk_ids = getattr(event, "chunk_ids", None) or ()
        chunk_id = str(chunk_ids[0]) if chunk_ids else str(getattr(event, "resource_id", "") or "")
        if not chunk_id:
            continue
        by_chunk.setdefault(chunk_id, []).append(str(getattr(event, "decision", "") or ""))

    reviewed_multiple_times = 0
    overturned = 0
    for decisions in by_chunk.values():
        if len(decisions) < 2:
            continue
        reviewed_multiple_times += 1
        if _OVERTURN_PAIR <= set(decisions):
            overturned += 1
    return {
        "reviewed_multiple_times": reviewed_multiple_times,
        "overturned": overturned,
        "review_overturn_rate": (
            (overturned / reviewed_multiple_times) if reviewed_multiple_times else 0.0
        ),
    }


_BLOCK_REASON_INVALID_CITATION = "APPROVED_CITATION_MISSING"


def answer_citation_quality_signals(
    citations: Iterable[object],
    *,
    is_high_risk: bool = False,
    blocked: bool = False,
    block_reason: str = "",
) -> dict[str, object]:
    """ADR-018 §18.4 — project extraction quality onto an answer's cited evidence.

    From the citations an answer actually used (each carrying the extraction-quality metadata the safety
    gate reads), report the quality-status distribution of the cited chunks, review-approved
    (``manual_approved``) chunk usage, how many citations are high-risk-citation eligible (§11.4), and
    whether THIS answer was a high-risk block due to a missing/ineligible approved citation. Pure over
    ``citation.metadata`` — the same SSOT the gate enforces — so the metric can't drift from the answer.
    """

    by_status: dict[str, int] = {}
    total = 0
    high_risk_eligible = 0
    for citation in citations:
        meta = getattr(citation, "metadata", None)
        status = _quality_status(_metadata_mapping(meta)) or QUALITY_STATUS_ACCEPTED
        by_status[status] = by_status.get(status, 0) + 1
        if is_high_risk_citation_quality_eligible(meta):
            high_risk_eligible += 1
        total += 1
    manual_approved_used = by_status.get(QUALITY_STATUS_MANUAL_APPROVED, 0)
    invalid_citation_block = (
        is_high_risk
        and blocked
        and str(block_reason or "").strip().upper() == _BLOCK_REASON_INVALID_CITATION
    )
    return {
        "citations_total": total,
        "by_status": by_status,
        "review_approved_chunk_usage": manual_approved_used,
        "review_approved_usage_rate": (manual_approved_used / total) if total else 0.0,
        "high_risk_citation_eligible": high_risk_eligible,
        "high_risk_blocked_invalid_citation": 1 if invalid_citation_block else 0,
    }


def aggregate_answer_quality_signals(
    signals: Iterable[Mapping[str, object]],
) -> dict[str, object]:
    """Roll up many per-answer §18.4 signal dicts into a dashboard snapshot (sums + rates)."""

    answers = 0
    citations_total = 0
    review_approved_usage = 0
    high_risk_eligible = 0
    high_risk_blocked = 0
    by_status: dict[str, int] = {}
    for s in signals:
        answers += 1
        citations_total += int(s.get("citations_total") or 0)
        review_approved_usage += int(s.get("review_approved_chunk_usage") or 0)
        high_risk_eligible += int(s.get("high_risk_citation_eligible") or 0)
        high_risk_blocked += int(s.get("high_risk_blocked_invalid_citation") or 0)
        for status, count in (s.get("by_status") or {}).items():
            by_status[str(status)] = by_status.get(str(status), 0) + int(count)
    return {
        "answers": answers,
        "citations_total": citations_total,
        "by_status": by_status,
        "review_approved_chunk_usage": review_approved_usage,
        "review_approved_usage_rate": (
            (review_approved_usage / citations_total) if citations_total else 0.0
        ),
        "high_risk_citation_eligible": high_risk_eligible,
        "high_risk_blocked_invalid_citation": high_risk_blocked,
    }


def _route_provider_and_fallback(route_trace: object) -> tuple[str, bool]:
    """From a persisted route_trace, return (winning provider, had a fallback step) for §18.1 metrics."""

    if not isinstance(route_trace, (list, tuple)):
        return "", False
    provider = ""
    had_fallback = False
    for step in route_trace:
        step_map = step if isinstance(step, Mapping) else {}
        if step_map.get("stage") == "fallback":
            had_fallback = True
        if step_map.get("provider"):
            provider = str(
                step_map.get("provider")
            )  # last named provider = the one that produced it
    return provider, had_fallback


def extraction_review_queue(
    store: object, *, tenant_id: str | None = None
) -> list[ExtractionReviewItem]:
    """Backend-agnostic review queue: an efficient JSONB filter on Postgres, else the in-mem projection.

    Prefers ``store.list_extraction_review_chunks()`` (ADR-018 A9, a metadata WHERE) when the store
    exposes it; otherwise projects over ``store.iter_items()``. Both read the same SSOT (stored quality
    metadata), so the result is identical — only the cost differs.
    """

    efficient = getattr(store, "list_extraction_review_chunks", None)
    if callable(efficient):
        try:
            chunks = efficient(tenant_id=tenant_id)  # PG: also sets the RLS session tenant
        except TypeError:
            chunks = efficient()
        return extraction_review_items(chunks, tenant_id=tenant_id)
    iter_items = getattr(store, "iter_items", None)
    if callable(iter_items):
        return extraction_review_items(iter_items(), tenant_id=tenant_id)
    return []


def _metadata_mapping(value: Mapping[str, object] | object | None) -> Mapping[str, object]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return value
    metadata = getattr(value, "metadata", None)
    if isinstance(metadata, Mapping):
        return metadata
    return {}


def _quality_status(metadata: Mapping[str, object]) -> str:
    return str(metadata.get(EXTRACTION_QUALITY_STATUS_KEY) or "").strip()


def _is_explicit_false(value: object) -> bool:
    if value is False:
        return True
    if isinstance(value, str):
        return value.strip().lower() in {"false", "0", "no"}
    return False
