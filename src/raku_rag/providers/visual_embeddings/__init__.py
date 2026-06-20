"""T068 - deterministic visual embedding provider."""

from __future__ import annotations

from typing import Sequence

from raku_rag.interfaces.base import Vector
from raku_rag.providers.embeddings import HashingEmbeddingProvider


class HashingVisualEmbeddingProvider:
    model_version = "hashing-visual-v1"

    def __init__(self, dim: int = 32) -> None:
        self.dim = dim
        self._inner = HashingEmbeddingProvider(dim=dim)

    def embed(self, regions: Sequence[bytes]) -> list[Vector]:
        texts = [region.decode("utf-8", errors="ignore") for region in regions]
        return self._inner.embed(texts)


__all__ = ["HashingVisualEmbeddingProvider"]
