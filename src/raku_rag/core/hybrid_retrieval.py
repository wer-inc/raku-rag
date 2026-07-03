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

from raku_rag.core.text import retrieval_tokens

HOT_IDENTIFIER_FIELDS: tuple[str, ...] = (
    "equipment_id",
    "alarm_code",
    "part_no",
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
# Recency is a TIE-BREAKER among content-equivalent chunks, not a content-overriding signal.
# Wave 1b measurement (docs/product/scale-bench.md): at 0.09 the boost exceeded the coverage
# margin separating the one on-topic document from same-family/same-component boilerplate
# (~0.35 × 3/18 ≈ 0.058), so newer near-miss documents crowded the true document out of the
# lexical leg's top_k at corpus scale (paraphrase recall@5 0.64@3k → 0.50@10k). 0.02 stays below
# a single content-term's coverage weight for realistic query lengths while still strictly
# ordering same-content chunks by effective/updated date.
LEXICAL_RECENCY_BOOST_MAX = 0.02
# Wave 1b (docs/product/scale-bench.md): weight for a business identifier from the query appearing
# VERBATIM in the chunk text — document numbers, part numbers etc. that are not in any hot metadata
# field, so the metadata-exact leg cannot see them. Without this an identifier is just 1-2 of ~17
# lexical terms: measured at N=3,000, the coverage edge of containing the queried doc number
# (~0.023) is smaller than the recency boost (0.09), so the ONE document that IS the queried number
# gets pushed out of the lexical leg's top_k by newer, boilerplate-similar documents. 0.18 per
# distinct matched identifier lifts a verbatim mention above any realistic prose-overlap score,
# while the LEXICAL_MATCH_MAX_SCORE cap keeps the leg strictly below METADATA_EXACT_MATCH_SCORE
# (a metadata exact match stays the strongest signal).
LEXICAL_IDENTIFIER_MATCH_WEIGHT = 0.18

_IDENTIFIER_RE = re.compile(
    r"(?<![A-Za-z0-9])"
    r"(?:"
    r"[A-Za-z]{1,16}(?:[-_][A-Za-z0-9]{1,24})+"
    r"|[A-Z]{2}[A-Z0-9]{9}\d"
    r"|[A-Za-z0-9]{2,24}\d[A-Za-z0-9]{1,24}"
    r")"
    r"(?![A-Za-z0-9])"
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


def matched_identifier_compacts(
    metadata: Mapping[str, Any] | object, identifiers: Iterable[str]
) -> frozenset[str]:
    """Compact canonical forms of the DISTINCT query identifiers matched by hot metadata fields.

    ``query_identifiers`` emits every extracted identifier in BOTH normalized ("eq-press-042") and
    compact ("eqpress042") form; deduplicating matches by compact form means one physical
    identifier never counts twice. Callers union the sets from several metadata sources (e.g.
    chunk + document metadata in the Postgres store) before taking ``len``.
    """
    identifier_set = frozenset(identifiers)
    if not identifier_set:
        return frozenset()
    matched: set[str] = set()
    for mapping in _metadata_mappings(metadata):
        for field in HOT_IDENTIFIER_FIELDS:
            value = mapping.get(field)
            if value is None:
                continue
            for identifier in identifier_set:
                compact = identifier.replace("-", "")
                if compact in matched:
                    continue
                if _value_matches(value, frozenset((identifier,))):
                    matched.add(compact)
    return frozenset(matched)


def metadata_identifier_match_count(
    metadata: Mapping[str, Any] | object, identifiers: Iterable[str]
) -> int:
    """Number of DISTINCT query identifiers matched (multiplicity for the metadata-exact leg).

    The metadata-exact leg assigns one flat ``METADATA_EXACT_MATCH_SCORE`` to every match, so a
    score alone cannot express that a chunk matching BOTH query identifiers (equipment id AND
    alarm code) is a stronger hit than a chunk matching only one. The stores rank the leg by this
    count (descending) before rank fusion, which is what breaks the measured flat-1.25 tie
    degeneration at corpus scale (docs/product/scale-bench.md).
    """
    return len(matched_identifier_compacts(metadata, identifiers))


def lexical_query_terms(query: str) -> tuple[str, ...]:
    """Content terms used by the lexical retrieval leg."""
    terms = {term.casefold() for term in retrieval_tokens(query) if _lexical_term_is_signal(term)}
    return tuple(sorted(terms))


def lexical_match_score(
    query: str, text: str, metadata: Mapping[str, Any] | object = None
) -> float:
    """Small BM25-like lexical score for keyword-dominant queries.

    This is deliberately bounded below ``METADATA_EXACT_MATCH_SCORE`` so exact business identifiers
    remain the strongest hybrid signal. It exists to rescue exact prose/code terms that the tiny local
    embedding model may not rank well, while staying storage-agnostic for Tier A.

    Business identifiers named by the query and appearing verbatim in the text (document numbers,
    part numbers — identifiers with no hot metadata field) additionally add
    ``LEXICAL_IDENTIFIER_MATCH_WEIGHT`` per DISTINCT matched identifier: extraction is symmetric
    (``query_identifiers`` on both sides, compact-form comparison), so "INS-0435" in the question
    matches "INS-0435。" in the text regardless of separators.
    """
    query_terms = lexical_query_terms(query)
    if not query_terms:
        return 0.0
    text_terms = retrieval_tokens(text)
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
    identifier_matches = _text_identifier_match_count(query, text)
    if identifier_matches:
        score += LEXICAL_IDENTIFIER_MATCH_WEIGHT * identifier_matches
    return min(LEXICAL_MATCH_MAX_SCORE, score)


def _text_identifier_match_count(query: str, text: str) -> int:
    """Distinct query identifiers appearing verbatim (compact-form) in the text."""
    query_compacts = {identifier.replace("-", "") for identifier in query_identifiers(query)}
    if not query_compacts:
        return 0
    text_compacts = {identifier.replace("-", "") for identifier in query_identifiers(text)}
    return len(query_compacts & text_compacts)


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


def _lexical_term_is_signal(term: str) -> bool:
    """Keep Japanese bigrams and compact equipment terms without admitting every tiny token."""
    if len(term) >= 3:
        return True
    if _contains_cjk(term):
        return True
    return len(term) >= 2 and any(ch.isdigit() for ch in term)


def _contains_cjk(term: str) -> bool:
    return any("\u3040" <= ch <= "\u30ff" or "\u3400" <= ch <= "\u9fff" for ch in term)


def _value_matches(value: object, identifiers: frozenset[str]) -> bool:
    if value is None:
        return False
    if isinstance(value, (list, tuple, set, frozenset)):
        return any(_value_matches(item, identifiers) for item in value)
    normalized = normalize_identifier(value)
    if not normalized:
        return False
    return normalized in identifiers or normalized.replace("-", "") in identifiers
