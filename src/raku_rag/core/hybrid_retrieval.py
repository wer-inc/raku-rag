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
from functools import lru_cache
from typing import Any, NamedTuple
from zlib import crc32

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
# Wave 1c (docs/product/scale-bench.md): coverage weight of a query term satisfied only through a
# tenant-approved synonym (``retrieval.synonyms`` lexicon namespace, expanded by
# services/retrieval.py for the LEXICAL leg only). Strictly < 1.0 — the ranking contract is that an
# expanded-term hit never outranks a direct-term hit at equal term coverage: a synonym-covered term
# contributes 0.9 of a direct term's coverage and contributes NOTHING to the frequency/density
# component, so at every equal coverage set the direct match scores strictly higher.
SYNONYM_COVERAGE_WEIGHT = 0.9


class SynonymExpansion(NamedTuple):
    """One tenant-approved synonym group as it applies to a specific query.

    ``source_terms``: the ORIGINAL query's lexical terms (``lexical_query_terms`` output — CJK
    bigrams / ASCII tokens) accounted for by the group member(s) found in the query. These are the
    terms a text may satisfy through a synonym.
    ``alternatives``: the group's OTHER members (casefolded phrases, e.g. the canonical document
    surface form) whose presence in a chunk text counts the source terms as synonym-covered.
    """

    source_terms: tuple[str, ...]
    alternatives: tuple[str, ...]


def synonym_expansions(
    query: str, groups: Mapping[str, Iterable[str]]
) -> tuple[SynonymExpansion, ...]:
    """Derive the lexical-leg synonym expansions of ``query`` from tenant lexicon ``groups``.

    ``groups`` is the ``retrieval.synonyms`` namespace: key = canonical term, values = synonyms.
    Matching is SYMMETRIC over the group ({key} ∪ values): whichever member the query used, the
    remaining members become alternatives — so a tenant may key the entry by the canonical
    document term (有給休暇: [年休]) and a query saying 年休 still expands to 有給休暇.

    Query-side membership: CJK members match as a substring of the casefolded query (Japanese has
    no word boundaries); ASCII members match on whole retrieval tokens (so "pto" never matches
    inside "laptop"). Deterministic output order (sorted group keys). Groups where no member — or
    every member — appears in the query contribute nothing.
    """
    query_cf = str(query or "").casefold()
    if not query_cf.strip() or not groups:
        return ()
    query_terms = lexical_query_terms(query)
    if not query_terms:
        return ()
    query_token_set = set(retrieval_tokens(query))
    expansions: list[SynonymExpansion] = []
    for key in sorted(str(k) for k in groups):
        raw_members = (key, *(str(v) for v in groups.get(key, ())))
        members = tuple(dict.fromkeys(m.strip().casefold() for m in raw_members if m and m.strip()))
        if len(members) < 2:
            continue
        matched = tuple(m for m in members if _phrase_present(m, query_cf, query_token_set))
        if not matched or len(matched) == len(members):
            continue
        source_terms = tuple(
            sorted({term for term in query_terms if any(term in m for m in matched)})
        )
        if not source_terms:
            continue
        alternatives = tuple(m for m in members if m not in matched)
        expansions.append(SynonymExpansion(source_terms=source_terms, alternatives=alternatives))
    return tuple(expansions)


def _phrase_present(phrase: str, haystack_cf: str, haystack_token_set: set[str]) -> bool:
    """Is ``phrase`` present in the casefolded haystack text / its retrieval-token set?

    CJK phrases: substring of the raw casefolded text (bigram tokenization cannot express phrase
    boundaries). ASCII phrases: every retrieval token of the phrase must be a whole haystack token
    (substring matching would false-positive, e.g. "pto" inside "laptop").
    """
    if _contains_cjk(phrase):
        return phrase in haystack_cf
    tokens = retrieval_tokens(phrase)
    return bool(tokens) and all(token in haystack_token_set for token in tokens)


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


def metadata_hot_identifier_compacts(metadata: Mapping[str, Any] | object) -> list[str]:
    """All hot-field identifier values of ``metadata`` in compact canonical form, sorted (0026).

    Ingest-time companion of ``matched_identifier_compacts``: the stores persist this set
    (``chunks.identifier_compacts`` / ``documents.identifier_compacts``) so the metadata-exact leg
    can match identifiers in SQL as a plain array overlap instead of evaluating dozens of
    lower()/regexp_replace expressions per row (the measured ~1.4s/query hot spot at N=10,000).
    EXACTNESS: ``_value_matches`` accepts a value iff its normalized OR compact form appears in the
    query set, which itself holds both forms of every query identifier — that is equivalent to
    compact(value) ∈ {compact(query identifier)}, so comparing compact sets is the SAME predicate,
    not a superset.
    """
    compacts: set[str] = set()
    for mapping in _metadata_mappings(metadata):
        for field in HOT_IDENTIFIER_FIELDS:
            value = mapping.get(field)
            if value is None:
                continue
            values = value if isinstance(value, (list, tuple, set, frozenset)) else (value,)
            for item in values:
                compact = compact_identifier(item)
                if compact:
                    compacts.add(compact)
    return sorted(compacts)


@lru_cache(maxsize=512)
def lexical_query_terms(query: str) -> tuple[str, ...]:
    """Content terms used by the lexical retrieval leg.

    Cached (Wave 1d): the lexical leg calls this once per CANDIDATE ROW via
    ``lexical_match_score`` — a pure per-query derivation repeated O(N) times was a measurable
    slice of the per-query Python cost at corpus scale (docs/product/scale-bench.md). The
    function is pure and returns an immutable tuple, so memoization is semantics-preserving.
    """
    terms = {term.casefold() for term in retrieval_tokens(query) if _lexical_term_is_signal(term)}
    return tuple(sorted(terms))


# Wave 1d lexical candidate-pool contract (docs/product/scale-bench.md §根本原因). The measured
# O(N) failure was NOT only the full-table transfer: on a shared-vocabulary manufacturing corpus
# ~94% of chunks contain at least one query term, so any "rows that could score > 0" predicate
# still transfers (and Python-tokenizes) nearly the whole tenant corpus per query. The leg's
# candidate contract is therefore, on BOTH stores (in-memory mirrors it exactly):
#
#   pool = the top max(top_k * LEXICAL_POOL_FACTOR, LEXICAL_POOL_MIN) ACL-VISIBLE candidate
#          chunks ordered by (distinct directly-matched query terms DESC, position, chunk_id);
#          the shared exact scorer then ranks the pool and top_k is taken from it.
#
# The match-count ordering key is exactly the scorer's dominant coverage component, so at pool
# sizes ≥ 50×top_k the exact top_k is preserved in practice (verified against the 3,000/10,000-doc
# bench: all quality slices within the ±0.02 tolerance). Corpora smaller than the pool floor —
# every Tier A test, the demo KB, the golden corpus — fetch every candidate, making the pool rule
# byte-identical to the pre-1d exhaustive behavior there. The Postgres store computes the pool in
# SQL over the ingest-time `lexical_token_hashes` column (migration 0026) so non-pool rows are
# never transferred; it falls back to the exhaustive Python path whenever the SQL pool cannot be
# trusted (ACL-invisible rows inside a truncated pool, or un-backfilled token hashes).
LEXICAL_POOL_FACTOR = 50
LEXICAL_POOL_MIN = 1000


def lexical_token_hash(token: str) -> int:
    """Stable 32-bit (signed, int4-compatible) hash of a retrieval token.

    Must be process- and version-stable because ingest WRITES these to Postgres
    (``chunks.lexical_token_hashes``) and query time re-derives them for SQL intersection — so
    zlib.crc32 (a fixed algorithm), never Python's salted ``hash()``. A collision can only ever
    ADD a row to the SQL candidate pool / bump its pool rank (the exact scorer re-ranks the pool
    on real tokens), never remove one.
    """
    value = crc32(token.encode("utf-8"))
    return value - 0x1_0000_0000 if value >= 0x8000_0000 else value


def lexical_token_hashes(text: str) -> list[int]:
    """Sorted DISTINCT token hashes of ``text`` — the ingest-time chunk column (0026).

    Uses the FULL retrieval token set (not the signal-filtered query terms): the scorer matches
    query terms against every retrieval token of the text, so the stored set must cover them all.
    Sorted for intarray's merge-based ``&``/``&&`` operators.

    A NON-empty text yielding zero tokens (punctuation-only) returns the ``[0]`` marker instead of
    ``[]``: the empty array is the '{}' *un-backfilled* sentinel that forces the whole tenant onto
    the exhaustive lexical path — a hashed-but-tokenless chunk must not look un-backfilled. The
    marker is harmless: a (rare) real crc32 of 0 in a query's candidate set would only over-select
    the row, and the exact scorer gives it 0 anyway.
    """
    hashes = sorted({lexical_token_hash(token) for token in retrieval_tokens(text)})
    if not hashes and str(text or "").strip():
        return [0]
    return hashes


def lexical_query_term_hashes(terms: Iterable[str]) -> list[int]:
    """Sorted hashes of the DIRECT query terms — the SQL pool-ordering array (match count)."""
    return sorted({lexical_token_hash(term) for term in terms})


def lexical_candidate_tokens(
    terms: Iterable[str], expansions: tuple[SynonymExpansion, ...] = ()
) -> frozenset[str]:
    """Tokens whose presence in a text's token set is NECESSARY for ``lexical_match_score`` > 0.

    score>0 requires a direct query term in the text's token set OR a synonym alternative present
    in the text: a present alternative implies ALL of its own retrieval tokens are in the text's
    token set (CJK alternatives as substrings imply their character bigrams; ASCII alternatives
    require whole-token presence), so ANY-of over this set over-selects and never under-selects.
    Both stores use it for pool eligibility; the Postgres store pushes its hashed form
    (``lexical_candidate_hashes``) into SQL.
    """
    tokens = {str(term) for term in terms if term}
    for expansion in expansions:
        for alternative in expansion.alternatives:
            tokens.update(retrieval_tokens(alternative))
    return frozenset(tokens)


def lexical_candidate_hashes(
    terms: Iterable[str], expansions: tuple[SynonymExpansion, ...] = ()
) -> list[int]:
    """Sorted hashes of ``lexical_candidate_tokens`` — the SQL candidacy array
    (``lexical_token_hashes && ...``)."""
    return sorted(
        lexical_token_hash(token) for token in lexical_candidate_tokens(terms, expansions)
    )


def lexical_direct_match_count(terms: Iterable[str], text_term_set: frozenset[str] | set) -> int:
    """DISTINCT direct query terms present in the text token set — the pool-ordering key.

    The in-memory store computes this on real tokens; the Postgres store computes the same count
    in SQL as ``icount(lexical_token_hashes & term_hashes)`` (hash collisions can only over-count,
    i.e. promote a row INTO the pool — never drop one).
    """
    return sum(1 for term in terms if term in text_term_set)


def lexical_match_score(
    query: str,
    text: str,
    metadata: Mapping[str, Any] | object = None,
    *,
    expansions: tuple[SynonymExpansion, ...] = (),
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

    ``expansions`` (Wave 1c, tenant-approved ``retrieval.synonyms`` only — see
    ``synonym_expansions``): a query term absent from the text still counts toward coverage when
    the text contains an alternative member of its synonym group, at ``SYNONYM_COVERAGE_WEIGHT``
    (< 1.0) and with NO frequency/density contribution — an expanded-term hit therefore never
    outranks a direct-term hit at equal term coverage. Empty ``expansions`` (every caller without
    a tenant lexicon) is byte-identical to the pre-1c score.
    """
    query_terms = lexical_query_terms(query)
    if not query_terms:
        return 0.0
    text_terms = retrieval_tokens(text)
    if not text_terms:
        return 0.0
    text_term_set = set(text_terms)
    matched = [term for term in query_terms if term in text_term_set]
    synonym_covered: set[str] = set()
    if expansions:
        unmatched = {term for term in query_terms if term not in text_term_set}
        if unmatched:
            text_cf = str(text).casefold()
            for expansion in expansions:
                coverable = unmatched.intersection(expansion.source_terms) - synonym_covered
                if not coverable:
                    continue
                if any(
                    _phrase_present(alt, text_cf, text_term_set) for alt in expansion.alternatives
                ):
                    synonym_covered |= coverable
    if not matched and not synonym_covered:
        return 0.0
    coverage = (len(matched) + SYNONYM_COVERAGE_WEIGHT * len(synonym_covered)) / len(query_terms)
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
    query_compacts = _query_identifier_compacts(query)
    if not query_compacts:
        return 0
    text_compacts = {identifier.replace("-", "") for identifier in query_identifiers(text)}
    return len(query_compacts & text_compacts)


@lru_cache(maxsize=512)
def _query_identifier_compacts(query: str) -> frozenset[str]:
    """Query-side identifier compacts, cached (Wave 1d): called once per candidate row by
    ``lexical_match_score`` but a pure function of the query — the per-row ``finditer`` over the
    query was pure repeated work. The text side stays uncached (one distinct text per row)."""
    return frozenset(identifier.replace("-", "") for identifier in query_identifiers(query))


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
