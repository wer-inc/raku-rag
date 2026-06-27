"""T026 — EmbeddingProvider. MVP: deterministic hashing bag-of-words (no external service).

Production swaps in OpenAI-compatible / Azure / local providers behind EmbeddingProvider.
Cosine similarity reflects token overlap → good enough for deterministic gate/integration tests.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Sequence

from raku_rag.core.text import retrieval_tokens as _tokens
from raku_rag.interfaces.base import EmbeddingProvider, Vector


@dataclass(frozen=True)
class EmbeddingCapability:
    provider: str
    model_version: str
    dimensions: int
    max_input_tokens: int = 0


class HashingEmbeddingProvider(EmbeddingProvider):
    model_version = "hashing-bow-v1"

    def __init__(self, dim: int = 256) -> None:
        self.dim = dim

    @property
    def capability(self) -> EmbeddingCapability:
        return EmbeddingCapability(
            provider="local",
            model_version=self.model_version,
            dimensions=self.dim,
            max_input_tokens=0,
        )

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * self.dim
        for tok in _tokens(text):
            h = int(hashlib.sha256(tok.encode()).hexdigest(), 16)
            v[h % self.dim] += 1.0
        norm = math.sqrt(sum(x * x for x in v))
        if norm:
            v = [x / norm for x in v]
        return v

    def embed(self, texts: Sequence[str]) -> list[Vector]:
        return [self._vec(t) for t in texts]


def embedding_dimension(provider: object) -> int:
    dim = getattr(provider, "dim", None)
    if dim is None:
        dim = getattr(provider, "dimensions", None)
    try:
        return int(dim or 0)
    except (TypeError, ValueError):
        return 0


def embedding_provider_from_settings(settings) -> EmbeddingProvider:
    provider_name = str(getattr(settings, "embedding_provider", "hashing") or "hashing")
    provider_name = provider_name.strip().lower().replace("-", "_")
    dim = int(getattr(settings, "embedding_dim", 256) or 256)
    profile = str(getattr(settings, "runtime_profile", "deterministic") or "deterministic")
    if profile.strip().lower() == "production" and provider_name in {
        "hashing",
        "hashing_bow",
        "hashing_bow_v1",
        "local",
    }:
        allow_hashing = bool(
            getattr(settings, "allow_hashing_embeddings_in_production", False)
        )
        if not allow_hashing:
            provider_name = "openai_text_embedding_3_small"
            if dim != 256:
                raise ValueError(
                    "production profile defaults to openai_text_embedding_3_small and requires "
                    f"embedding_dim=256; got {dim}."
                )
    if provider_name in {"hashing", "hashing_bow", "hashing_bow_v1", "local"}:
        return HashingEmbeddingProvider(dim=dim)
    if provider_name in {"bedrock_cohere_multilingual_v3", "cohere_embed_multilingual_v3"}:
        if dim != 1024:
            raise ValueError(
                "bedrock_cohere_multilingual_v3 requires embedding_dim=1024; "
                f"got {dim}. Reindex and use a matching vector schema before switching."
            )
        from workers.ingest.providers.embeddings.bedrock_cohere import (
            CohereEmbedMultilingualV3Provider,
        )

        region = str(getattr(settings, "aws_region", "us-east-1") or "us-east-1")
        return CohereEmbedMultilingualV3Provider(region_name=region)  # type: ignore[return-value]
    if provider_name in {
        "openai_text_embedding_3_small",
        "openai_text_embedding_3_large",
        "text_embedding_3_small",
        "text_embedding_3_large",
    }:
        # Matryoshka `dimensions` lets text-embedding-3 emit `dim`-wide vectors, so dim=256 fits the
        # existing vector(256) chunks column with NO schema migration. The API key comes from
        # settings/OPENAI_API_KEY; the provider reads env when not injected.
        import os

        from workers.ingest.providers.embeddings.openai_embed3 import OpenAIEmbedding3Provider

        model = "text-embedding-3-large" if "large" in provider_name else "text-embedding-3-small"
        api_key = str(
            getattr(settings, "openai_api_key", "") or os.environ.get("OPENAI_API_KEY", "")
        )
        return OpenAIEmbedding3Provider(model=model, dimensions=dim, api_key=api_key)  # type: ignore[return-value]
    raise ValueError(f"unsupported embedding_provider: {provider_name!r}")


def cosine(a: Vector, b: Vector) -> float:
    return sum(x * y for x, y in zip(a, b))  # inputs already L2-normalized
