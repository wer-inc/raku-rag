"""OpenAI ``text-embedding-3`` adapter (stdlib HTTP, dependency-free).

Deliberately small, mirroring the Bedrock Cohere adapter's seam: it validates inputs, calls the
OpenAI embeddings REST API via ``urllib``, and accepts an INJECTED transport in tests (no network,
no API key). It uses the ``dimensions`` parameter (Matryoshka) so ``text-embedding-3-small`` can
emit 256-dim vectors that fit the existing ``vector(256)`` chunks column — NO schema migration.

Vectors are L2-normalized here because Matryoshka-truncated embeddings are not unit-length, and the
project's ``cosine()`` (providers/embeddings.py) is a bare dot product that assumes normalized
inputs. The API key is read from ``OPENAI_API_KEY`` when not injected; it is never logged.
"""

from __future__ import annotations

import json
import math
import os
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

Vector = Sequence[float]

# Injectable seam: (url, headers, body_bytes, timeout) -> parsed JSON dict. Tests pass a fake.
Transport = Callable[[str, dict, bytes, float], dict]


def _https_transport(url: str, headers: dict, body: bytes, timeout: float) -> dict:
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - fixed https endpoint
        return json.loads(resp.read().decode("utf-8"))


@dataclass
class OpenAIEmbedding3Provider:
    api_key: str = ""
    model: str = "text-embedding-3-small"
    dimensions: int = 256
    base_url: str = "https://api.openai.com/v1"
    timeout: float = 30.0
    transport: Transport | None = None
    model_version: str = field(init=False, default="")

    def __post_init__(self) -> None:
        self.model_version = f"openai:{self.model}:{self.dimensions}"
        if not self.api_key:
            self.api_key = os.environ.get("OPENAI_API_KEY", "")

    def embed(self, texts: Sequence[str]) -> list[Vector]:
        items = list(texts)
        if not items:
            return []
        if not self.api_key:
            raise RuntimeError("openai_api_key_missing: set OPENAI_API_KEY for text-embedding-3")
        body = json.dumps(
            {"model": self.model, "input": items, "dimensions": self.dimensions}
        ).encode("utf-8")
        headers = {
            "content-type": "application/json",
            "authorization": f"Bearer {self.api_key}",
        }
        transport = self.transport or _https_transport
        payload = transport(f"{self.base_url}/embeddings", headers, body, self.timeout)
        data = sorted(payload.get("data") or [], key=lambda d: d.get("index", 0))
        if len(data) != len(items):
            raise ValueError(
                f"openai embeddings count mismatch: expected {len(items)}, got {len(data)}"
            )
        return [self._normalize(item.get("embedding")) for item in data]

    def _normalize(self, vec: object) -> Vector:
        if vec is None or isinstance(vec, (str, bytes, bytearray)) or not isinstance(vec, Sequence):
            raise ValueError("openai embedding item is not a vector")
        if len(vec) != self.dimensions:
            raise ValueError(
                f"embedding dimension mismatch: expected {self.dimensions}, got {len(vec)}"
            )
        floats = [float(x) for x in vec]
        norm = math.sqrt(sum(x * x for x in floats))
        if norm:
            floats = [x / norm for x in floats]
        return tuple(floats)
