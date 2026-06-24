"""T027 — Reranker. MVP: score-order reranker with a fail-safe contract.

On failure the caller falls back to the un-reranked results (FR-030); only proceeds to answer if
they still meet the threshold/evidence requirements.
"""

from __future__ import annotations

from typing import Callable, Sequence

from raku_rag.domain.models import ScoredChunk
from raku_rag.interfaces.base import Reranker


class ScoreOrderReranker(Reranker):
    def rerank(self, query: str, scored: Sequence[ScoredChunk], top_n: int) -> list[ScoredChunk]:
        return sorted(scored, key=lambda s: s.retrieval_score, reverse=True)[:top_n]


# Invoker seam: (query, documents) -> relevance scores aligned to documents. Injected so the provider is
# unit-testable offline (mock) and so boto3/credentials live at the edge.
RerankInvoker = Callable[..., Sequence[float]]


class BedrockCohereReranker(Reranker):
    """Production reranker over Amazon Bedrock (Cohere rerank). The Bedrock round-trip is the injected
    ``invoker``. Per the reranker FR-030 contract, reranking is fail-SAFE: if no invoker is configured or
    the call fails, it falls back to score-order — never blocking the answer. This is distinct from the
    LLM's fail-closed posture because rerank is a quality enhancement, not a safety gate (the
    groundedness/safety gates still run on the candidates regardless of order).
    """

    model = "cohere.rerank-v3-5:0"

    def __init__(self, *, invoker: RerankInvoker | None = None) -> None:
        self._invoker = invoker

    def rerank(self, query: str, scored: Sequence[ScoredChunk], top_n: int) -> list[ScoredChunk]:
        ordered = sorted(scored, key=lambda s: s.retrieval_score, reverse=True)
        if self._invoker is None or not ordered:
            return ordered[:top_n]
        try:
            relevances = list(self._invoker(query=query, documents=[s.chunk.text for s in ordered]))
        except Exception:
            return ordered[:top_n]  # FR-030 fail-safe: degrade to score-order, never block
        if len(relevances) != len(ordered):
            return ordered[:top_n]
        reranked = [
            s for _, s in sorted(zip(relevances, ordered), key=lambda t: t[0], reverse=True)
        ]
        return reranked[:top_n]


def reranker_from_settings(settings, *, invoker: RerankInvoker | None = None) -> Reranker:
    """Select the reranker by runtime profile (P1-3). deterministic -> ScoreOrderReranker;
    production -> BedrockCohereReranker (fail-safe to score-order without an invoker, per FR-030).
    """
    profile = str(getattr(settings, "runtime_profile", "deterministic") or "deterministic")
    profile = profile.strip().lower()
    if profile in {"deterministic", "mvp", "offline", ""}:
        return ScoreOrderReranker()
    if profile == "production":
        return BedrockCohereReranker(invoker=invoker)
    raise ValueError(f"unsupported runtime_profile: {profile!r}")
