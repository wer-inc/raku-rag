"""Identifier-aware retrieval helpers for the core RAG path.

The production-risk item this module addresses is narrow: queries that name an exact business
identifier (equipment IDs, alarm codes, ISINs, contract IDs, etc.) must not rely on semantic vector
similarity alone. These helpers stay storage-agnostic so both the in-memory and Postgres stores can
share the same identifier extraction/matching semantics.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from typing import Any

from raku_rag.core.text import content_tokens

HOT_IDENTIFIER_FIELDS: tuple[str, ...] = (
    "equipment_id",
    "alarm_code",
    "property_id",
    "room_number",
    "contract_id",
    "fund_id",
    "isin",
    "invoice_id",
)

NESTED_METADATA_KEYS: tuple[str, ...] = (
    "_mfg_meta",
    "manufacturing_metadata",
    "manufacturing",
    "industry_metadata",
)

METADATA_EXACT_MATCH_SCORE = 1.25
LEXICAL_MATCH_BASE_SCORE = 0.70
LEXICAL_MATCH_MAX_SCORE = 1.20
LEXICAL_RECENCY_BOOST_MAX = 0.09

_IDENTIFIER_RE = re.compile(
    r"\b[A-Za-z]{1,16}(?:[-_][A-Za-z0-9]{1,24})+\b"
    r"|\b[A-Z]{2}[A-Z0-9]{9}\d\b"
    r"|\b[A-Za-z0-9]{2,24}\d[A-Za-z0-9]{1,24}\b"
)
_NON_IDENTIFIER_CHARS = re.compile(r"[^a-z0-9]+")


def normalize_identifier(value: object) -> str:
    """Return a comparable exact-match identifier form."""
    text = str(value or "").strip().casefold()
    text = _NON_IDENTIFIER_CHARS.sub("-", text)
    return text.strip("-")


def compact_identifier(value: object) -> str:
    """Return the same identifier without separators."""
    return normalize_identifier(value).replace("-", "")


def query_identifiers(query: str) -> tuple[str, ...]:
    """Extract likely business identifiers from a user query.

    The rule intentionally requires a digit or an explicit separator so normal prose words do not
    become exact-match filters.
    """
    identifiers: set[str] = set()
    for match in _IDENTIFIER_RE.finditer(query):
        normalized = normalize_identifier(match.group(0))
        compact = normalized.replace("-", "")
        if len(compact) < 3:
            continue
        if "-" not in normalized and not any(ch.isdigit() for ch in compact):
            continue
        identifiers.add(normalized)
        identifiers.add(compact)
    return tuple(sorted(identifiers))


def metadata_identifier_matches(
    metadata: Mapping[str, Any] | object, identifiers: Iterable[str]
) -> bool:
    """Return true when any hot identifier field exactly matches the query identifiers."""
    identifier_set = frozenset(identifiers)
    if not identifier_set:
        return False
    for mapping in _metadata_mappings(metadata):
        for field in HOT_IDENTIFIER_FIELDS:
            if _value_matches(mapping.get(field), identifier_set):
                return True
    return False


def lexical_query_terms(query: str) -> tuple[str, ...]:
    """Content terms used by the lexical retrieval leg."""
    terms = {term.casefold() for term in content_tokens(query) if len(term) >= 3}
    return tuple(sorted(terms))


def lexical_match_score(
    query: str, text: str, metadata: Mapping[str, Any] | object = None
) -> float:
    """Small BM25-like lexical score for keyword-dominant queries.

    This is deliberately bounded below ``METADATA_EXACT_MATCH_SCORE`` so exact business identifiers
    remain the strongest hybrid signal. It exists to rescue exact prose/code terms that the tiny local
    embedding model may not rank well, while staying storage-agnostic for Tier A.
    """
    query_terms = lexical_query_terms(query)
    if not query_terms:
        return 0.0
    text_terms = content_tokens(text)
    if not text_terms:
        return 0.0
    text_term_set = set(text_terms)
    matched = [term for term in query_terms if term in text_term_set]
    if not matched:
        return 0.0
    coverage = len(matched) / len(query_terms)
    frequency = sum(min(text_terms.count(term), 3) for term in matched)
    density = min(1.0, frequency / max(1, len(text_terms)))
    score = LEXICAL_MATCH_BASE_SCORE + (0.35 * coverage) + (0.06 * density)
    score += recency_boost(metadata)
    return min(LEXICAL_MATCH_MAX_SCORE, score)


def recency_boost(metadata: Mapping[str, Any] | object = None) -> float:
    """Return a bounded boost for newer effective/updated metadata dates."""
    date_value = _metadata_date_value(metadata)
    if not date_value:
        return 0.0
    try:
        dt = datetime.fromisoformat(str(date_value).replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    age_days = max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 86_400)
    return max(0.0, 1.0 - (age_days / 3650.0)) * LEXICAL_RECENCY_BOOST_MAX


def _metadata_mappings(value: object, *, _depth: int = 0) -> tuple[Mapping[str, Any], ...]:
    if _depth > 3:
        return ()
    mapping = _as_mapping(value)
    if mapping is None:
        return ()

    mappings: list[Mapping[str, Any]] = [mapping]
    for key in NESTED_METADATA_KEYS:
        child = mapping.get(key)
        mappings.extend(_metadata_mappings(child, _depth=_depth + 1))
    return tuple(mappings)


def _as_mapping(value: object) -> Mapping[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, Mapping):
        return value
    to_mapping = getattr(value, "to_mapping", None)
    if callable(to_mapping):
        mapped = to_mapping()
        return mapped if isinstance(mapped, Mapping) else None
    return None


def _metadata_date_value(metadata: Mapping[str, Any] | object = None) -> object:
    for mapping in _metadata_mappings(metadata):
        for key in ("effective_date", "updated_at", "indexed_at", "created_at", "revision_date"):
            value = mapping.get(key)
            if value:
                return value
    return None


def _value_matches(value: object, identifiers: frozenset[str]) -> bool:
    if value is None:
        return False
    if isinstance(value, (list, tuple, set, frozenset)):
        return any(_value_matches(item, identifiers) for item in value)
    normalized = normalize_identifier(value)
    if not normalized:
        return False
    return normalized in identifiers or normalized.replace("-", "") in identifiers
