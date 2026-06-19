"""T026 — EmbeddingProvider. MVP: deterministic hashing bag-of-words (no external service).

Production swaps in OpenAI-compatible / Azure / local providers behind EmbeddingProvider.
Cosine similarity reflects token overlap → good enough for deterministic gate/integration tests.
"""
from __future__ import annotations

import hashlib
import math
from typing import Sequence

from raku_rag.core.text import content_tokens as _tokens
from raku_rag.interfaces.base import EmbeddingProvider, Vector


class HashingEmbeddingProvider(EmbeddingProvider):
    model_version = "hashing-bow-v1"

    def __init__(self, dim: int = 256) -> None:
        self.dim = dim

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


def cosine(a: Vector, b: Vector) -> float:
    return sum(x * y for x, y in zip(a, b))  # inputs already L2-normalized
