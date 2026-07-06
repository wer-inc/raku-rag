"""Extraction quality metadata and retrieval eligibility helpers.

The ingestion pipeline can add stronger parsers over time, but retrieval and answer generation need
one stable contract: chunks that still require extraction review must not become evidence.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

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

    body = text or ""
    stripped = body.strip()
    hard_reasons: list[str] = []
    soft_reasons: list[str] = []

    if (raw_size or 0) >= _EMPTY_YIELD_MIN_RAW_BYTES and len(stripped) < _MIN_TEXT_YIELD_CHARS:
        hard_reasons.append(REASON_EMPTY_EXTRACTION)

    if "(cid:" in body:
        hard_reasons.append(REASON_CID_ARTIFACTS)

    if body:
        replacement_ratio = body.count("�") / len(body)
        control_chars = sum(1 for ch in body if ord(ch) < 32 and ch not in "\t\n\r")
        control_ratio = control_chars / len(body)
        if replacement_ratio >= _MOJIBAKE_HARD_RATIO or control_ratio >= _CONTROL_CHAR_HARD_RATIO:
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


def is_high_risk_citation_quality_eligible(metadata: Mapping[str, object] | object | None) -> bool:
    """Return whether extraction quality allows a chunk to be high-risk manufacturing evidence."""

    values = _metadata_mapping(metadata)
    if not is_retrieval_eligible(values):
        return False
    if _is_explicit_false(values.get(HIGH_RISK_CITATION_ELIGIBLE_KEY)):
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
        reasons = _metadata_mapping(metadata).get(EXTRACTION_QUALITY_REASONS_KEY) or ()
        queue.append(
            ExtractionReviewItem(
                tenant_id=str(getattr(chunk, "tenant_id", "") or ""),
                document_id=str(getattr(chunk, "document_id", "") or ""),
                chunk_id=str(getattr(chunk, "chunk_id", "") or ""),
                status=status,
                reasons=tuple(str(reason) for reason in reasons if reason),
            )
        )
    return queue


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
