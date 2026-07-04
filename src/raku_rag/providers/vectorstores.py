"""T019 — VectorStore. MVP in-memory analog of the pgvector adapter.

CRITICAL invariant (FR-022, SC-003/004, SC-009): search applies tenant_id, tombstone exclusion
and the ACL ``visible`` predicate as a PRE-filter, BEFORE scoring — never post-filter only. The
production pgvector adapter expresses the same filter as a SQL WHERE clause.
"""

from __future__ import annotations

from typing import Sequence

from raku_rag.core import hybrid_retrieval  # module ref: pool constants stay patchable in tests
from raku_rag.core.hybrid_retrieval import (
    lexical_candidate_tokens,
    lexical_direct_match_count,
    lexical_match_score,
    lexical_query_terms,
    METADATA_EXACT_MATCH_SCORE,
    metadata_identifier_match_count,
    query_identifiers,
    SynonymExpansion,
)
from raku_rag.core.text import retrieval_tokens
from raku_rag.domain.models import Chunk, Modality, ScoredChunk
from raku_rag.interfaces.base import VectorStore, Vector, VisibilityPredicate
from raku_rag.providers.embeddings import cosine


class InMemoryVectorStore(VectorStore):
    def __init__(self) -> None:
        # chunk_id -> (Chunk, vector)
        self._items: dict[str, tuple[Chunk, Vector]] = {}
        # observability for tests: how many candidates were considered after pre-filter
        self.last_prefiltered_count: int = 0

    def upsert(self, chunks: Sequence[tuple[Chunk, Vector]]) -> None:
        for chunk, vec in chunks:
            self._items[chunk.chunk_id] = (chunk, vec)

    def iter_items(self) -> tuple[tuple[Chunk, Vector], ...]:
        """All stored (chunk, vector) pairs — the in-memory bulk accessor.

        A public seam for callers that need to scan the whole store (e.g. metadata propagation,
        the manufacturing ACL-denial survey) so they don't reach into the private ``_items`` dict.
        """
        return tuple(self._items.values())

    def search(
        self,
        tenant_id: str,
        query_vec: Vector,
        *,
        visible: VisibilityPredicate,
        top_k: int,
    ) -> list[ScoredChunk]:
        candidates: list[tuple[Chunk, Vector]] = []
        for chunk, vec in self._items.values():
            # PRE-filter: tenant boundary + tombstone + ACL visibility (deny-by-default)
            if chunk.tenant_id != tenant_id:
                continue
            if chunk.tombstone:
                continue
            if not visible(chunk):
                continue
            candidates.append((chunk, vec))
        self.last_prefiltered_count = len(candidates)
        scored = [ScoredChunk(chunk=c, retrieval_score=cosine(query_vec, v)) for c, v in candidates]
        scored.sort(key=lambda s: s.retrieval_score, reverse=True)
        return scored[:top_k]

    def metadata_exact_matches(
        self,
        tenant_id: str,
        query: str,
        *,
        visible: VisibilityPredicate,
        top_k: int,
    ) -> list[ScoredChunk]:
        """Return ACL-visible chunks whose hot metadata identifiers exactly match the query.

        The leg is RANKED by identifier match multiplicity (how many distinct query identifiers
        the chunk matches, descending) so rank fusion in the retrieval service can separate a
        chunk matching BOTH identifiers from the flat-score crowd matching only one; position and
        chunk_id keep the order deterministic within one multiplicity. The score itself stays the
        flat ``METADATA_EXACT_MATCH_SCORE`` (absolute-scale contract for the groundedness gate).
        """
        identifiers = query_identifiers(query)
        if not identifiers or top_k <= 0:
            return []
        matches: list[tuple[int, ScoredChunk]] = []
        for chunk, _vec in self._items.values():
            if chunk.tenant_id != tenant_id:
                continue
            if chunk.tombstone:
                continue
            if not visible(chunk):
                continue
            match_count = metadata_identifier_match_count(chunk.metadata, identifiers)
            if match_count <= 0:
                continue
            matches.append(
                (match_count, ScoredChunk(chunk=chunk, retrieval_score=METADATA_EXACT_MATCH_SCORE))
            )
        matches.sort(key=lambda item: (-item[0], item[1].chunk.position, item[1].chunk.chunk_id))
        return [scored for _count, scored in matches[:top_k]]

    def lexical_matches(
        self,
        tenant_id: str,
        query: str,
        *,
        visible: VisibilityPredicate,
        top_k: int,
        expansions: tuple[SynonymExpansion, ...] = (),
    ) -> list[ScoredChunk]:
        """Return ACL-visible chunks with direct lexical term overlap.

        Wave 1d: mirrors the shared candidate-pool contract
        (``core.hybrid_retrieval.LEXICAL_POOL_FACTOR``/``LEXICAL_POOL_MIN``) — only the top
        ``max(top_k*factor, min)`` ACL-visible candidates by (distinct directly-matched query
        terms DESC, position, chunk_id) are exactly scored, keeping this store behaviorally
        aligned with the Postgres store's SQL pool at corpus scale. Every corpus smaller than the
        pool floor (all Tier A fixtures) fetches the whole candidate set, i.e. the pre-1d
        behavior byte-for-byte.

        ``expansions`` (Wave 1c): tenant-approved synonym groups from ``retrieval.synonyms``
        (see ``core.hybrid_retrieval.synonym_expansions``) — forwarded verbatim to the shared
        scorer so the in-memory and Postgres stores stay behaviorally aligned. Default () is
        byte-identical to the pre-1c leg.
        """
        if top_k <= 0:
            return []
        terms = lexical_query_terms(query)
        if not terms:
            return []  # the shared scorer returns 0.0 for every chunk without query terms
        candidate_tokens = lexical_candidate_tokens(terms, expansions)
        pool_limit = max(
            top_k * hybrid_retrieval.LEXICAL_POOL_FACTOR, hybrid_retrieval.LEXICAL_POOL_MIN
        )
        pool: list[tuple[int, Chunk]] = []
        for chunk, _vec in self._items.values():
            if chunk.tenant_id != tenant_id:
                continue
            if chunk.tombstone:
                continue
            if not visible(chunk):
                continue
            text_term_set = set(retrieval_tokens(chunk.text))
            if candidate_tokens.isdisjoint(text_term_set):
                continue  # cannot score > 0 (necessary-condition check, same as the SQL &&)
            pool.append((lexical_direct_match_count(terms, text_term_set), chunk))
        pool.sort(key=lambda item: (-item[0], item[1].position, item[1].chunk_id))
        matches: list[ScoredChunk] = []
        for _count, chunk in pool[:pool_limit]:
            score = lexical_match_score(query, chunk.text, chunk.metadata, expansions=expansions)
            if score <= 0:
                continue
            matches.append(ScoredChunk(chunk=chunk, retrieval_score=score))
        matches.sort(key=lambda s: (-s.retrieval_score, s.chunk.position, s.chunk.chunk_id))
        return matches[:top_k]

    def set_tombstone(self, tenant_id: str, document_id: str, value: bool) -> int:
        n = 0
        for cid, (chunk, vec) in list(self._items.items()):
            if chunk.tenant_id == tenant_id and chunk.document_id == document_id:
                chunk.tombstone = value
                n += 1
        return n

    def purge(self, tenant_id: str, document_id: str) -> int:
        to_del = [
            cid
            for cid, (chunk, _) in self._items.items()
            if chunk.tenant_id == tenant_id and chunk.document_id == document_id
        ]
        for cid in to_del:
            del self._items[cid]
        return len(to_del)

    def visual_chunks_for_asset(self, tenant_id: str, asset_id: str) -> tuple[Chunk, ...]:
        return tuple(
            chunk
            for chunk, _ in self._items.values()
            if chunk.tenant_id == tenant_id
            and not chunk.tombstone
            and (chunk.modality == Modality.VISUAL or str(chunk.modality) == Modality.VISUAL.value)
            and str(chunk.metadata.get("asset_id", "")) == asset_id
        )

    def visual_chunks_for_document(self, tenant_id: str, document_id: str) -> tuple[Chunk, ...]:
        return tuple(
            chunk
            for chunk, _ in self._items.values()
            if chunk.tenant_id == tenant_id
            and chunk.document_id == document_id
            and not chunk.tombstone
            and (chunk.modality == Modality.VISUAL or str(chunk.modality) == Modality.VISUAL.value)
        )
