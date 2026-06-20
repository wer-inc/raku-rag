"""Bedrock Cohere Embed Multilingual v3 adapter.

The adapter is deliberately small: it validates token limits before any network call and accepts an
injected Bedrock Runtime client in tests. In production, pass a boto3 bedrock-runtime client or let
the provider create one lazily when boto3 is installed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Callable, Sequence

from workers.ingest.provider_policy import ProviderCapability

Vector = Sequence[float]


def estimate_tokens(text: str) -> int:
    word_count = len(text.split())
    char_count = max(1, len(text) // 4)
    return max(word_count, char_count)


@dataclass(frozen=True)
class RechunkPlan:
    reason: str
    text_index: int
    observed_tokens: int
    max_input_tokens: int
    target_tokens: int = 350
    max_tokens: int = 450

    def to_dict(self) -> dict:
        return {
            "reason": self.reason,
            "text_index": self.text_index,
            "observed_tokens": self.observed_tokens,
            "max_input_tokens": self.max_input_tokens,
            "target_tokens": self.target_tokens,
            "max_tokens": self.max_tokens,
        }


class RechunkRequired(ValueError):
    def __init__(self, plan: RechunkPlan) -> None:
        super().__init__(plan.reason)
        self.plan = plan


@dataclass
class CohereEmbedMultilingualV3Provider:
    client: object | None = None
    region_name: str = "us-east-1"
    model_id: str = "cohere.embed-multilingual-v3"
    dimensions: int = 1024
    max_input_tokens: int = 512
    client_factory: Callable[[str], object] | None = None
    model_version: str = field(init=False, default="bedrock:cohere.embed-multilingual-v3")

    @property
    def capability(self) -> ProviderCapability:
        return ProviderCapability(
            provider="bedrock",
            provider_family="aws",
            region=self.region_name,
            zero_retention=True,
            no_train=True,
        )

    def embed(self, texts: Sequence[str], *, input_type: str = "search_document") -> list[Vector]:
        self._validate_lengths(texts)
        body = {
            "texts": list(texts),
            "input_type": input_type,
            "embedding_types": ["float"],
        }
        response = self._client().invoke_model(
            modelId=self.model_id,
            body=json.dumps(body).encode("utf-8"),
            accept="application/json",
            contentType="application/json",
        )
        payload = json.loads(response["body"].read().decode("utf-8"))
        return self._parse_embeddings(payload)

    def _validate_lengths(self, texts: Sequence[str]) -> None:
        for index, text in enumerate(texts):
            tokens = estimate_tokens(text)
            if tokens > self.max_input_tokens:
                raise RechunkRequired(
                    RechunkPlan(
                        reason="chunk_overflow_requires_rechunk",
                        text_index=index,
                        observed_tokens=tokens,
                        max_input_tokens=self.max_input_tokens,
                    )
                )

    def _client(self):
        if self.client is not None:
            return self.client
        if self.client_factory is not None:
            self.client = self.client_factory(self.region_name)
            return self.client
        try:
            import boto3  # type: ignore
        except (
            ModuleNotFoundError
        ) as exc:  # pragma: no cover - exercised only without injected client
            raise RuntimeError("boto3 is required for Bedrock embedding calls") from exc
        self.client = boto3.client("bedrock-runtime", region_name=self.region_name)
        return self.client

    def _parse_embeddings(self, payload: dict) -> list[Vector]:
        raw = payload.get("embeddings") or []
        vectors: list[Vector] = []
        for item in raw:
            vector = item.get("float") if isinstance(item, dict) else item
            if len(vector) != self.dimensions:
                raise ValueError(
                    f"embedding dimension mismatch: expected {self.dimensions}, got {len(vector)}"
                )
            vectors.append(tuple(float(value) for value in vector))
        return vectors
