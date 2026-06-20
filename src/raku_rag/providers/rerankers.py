"""T027 — Reranker. MVP: score-order reranker with a fail-safe contract.

On failure the caller falls back to the un-reranked results (FR-030); only proceeds to answer if
they still meet the threshold/evidence requirements.
"""

from __future__ import annotations

from typing import Sequence

from raku_rag.domain.models import ScoredChunk
from raku_rag.interfaces.base import Reranker


class ScoreOrderReranker(Reranker):
    def rerank(self, query: str, scored: Sequence[ScoredChunk], top_n: int) -> list[ScoredChunk]:
        return sorted(scored, key=lambda s: s.retrieval_score, reverse=True)[:top_n]
