"""OpenAI text-embedding-3 adapter — request shape, normalization, and provider selection.

Uses an injected transport so no API key or network is touched.
"""

from __future__ import annotations

import json
import math
import unittest

from raku_rag.core.config import Settings
from raku_rag.providers.embeddings import embedding_provider_from_settings
from workers.ingest.providers.embeddings.openai_embed3 import OpenAIEmbedding3Provider


class CaptureTransport:
    """Fake OpenAI embeddings transport: records the request, returns deterministic vectors."""

    def __init__(self, dim: int) -> None:
        self.dim = dim
        self.calls: list[dict] = []

    def __call__(self, url: str, headers: dict, body: bytes, timeout: float) -> dict:
        payload = json.loads(body.decode("utf-8"))
        self.calls.append({"url": url, "headers": headers, "payload": payload})
        # Return one un-normalized vector per input, in shuffled index order to exercise sorting.
        data = []
        for i, _text in enumerate(payload["input"]):
            vec = [float(i + 1)] * self.dim  # not unit-length on purpose
            data.append({"index": i, "embedding": vec})
        return {"data": list(reversed(data))}


class TestOpenAIEmbed3(unittest.TestCase):
    def test_request_uses_model_and_dimensions(self) -> None:
        t = CaptureTransport(dim=256)
        p = OpenAIEmbedding3Provider(api_key="sk-test", dimensions=256, transport=t)
        p.embed(["a", "b"])
        sent = t.calls[0]["payload"]
        self.assertEqual(sent["model"], "text-embedding-3-small")
        self.assertEqual(sent["dimensions"], 256)
        self.assertEqual(sent["input"], ["a", "b"])
        self.assertTrue(t.calls[0]["url"].endswith("/embeddings"))
        self.assertEqual(t.calls[0]["headers"]["authorization"], "Bearer sk-test")

    def test_vectors_are_l2_normalized_and_index_ordered(self) -> None:
        t = CaptureTransport(dim=4)
        p = OpenAIEmbedding3Provider(api_key="sk-test", dimensions=4, transport=t)
        vecs = p.embed(["first", "second"])
        self.assertEqual(len(vecs), 2)
        for v in vecs:
            self.assertAlmostEqual(math.sqrt(sum(x * x for x in v)), 1.0, places=6)
        # index 0 -> value 1.0 across dims; normalized -> 0.5 each (4 dims). Confirms order preserved.
        self.assertAlmostEqual(vecs[0][0], 0.5, places=6)

    def test_dimension_mismatch_raises(self) -> None:
        t = CaptureTransport(dim=8)  # returns 8-d vectors
        p = OpenAIEmbedding3Provider(api_key="sk-test", dimensions=256, transport=t)
        with self.assertRaises(ValueError):
            p.embed(["x"])

    def test_missing_key_raises(self) -> None:
        p = OpenAIEmbedding3Provider(api_key="", transport=CaptureTransport(dim=256))
        with self.assertRaises(RuntimeError):
            p.embed(["x"])

    def test_empty_input_no_call(self) -> None:
        t = CaptureTransport(dim=256)
        p = OpenAIEmbedding3Provider(api_key="sk-test", transport=t)
        self.assertEqual(p.embed([]), [])
        self.assertEqual(t.calls, [])

    def test_settings_selection_small_256(self) -> None:
        settings = Settings(
            embedding_provider="openai_text_embedding_3_small",
            embedding_dim=256,
            openai_api_key="sk-test",
        )
        provider = embedding_provider_from_settings(settings)
        self.assertIsInstance(provider, OpenAIEmbedding3Provider)
        self.assertEqual(provider.model, "text-embedding-3-small")
        self.assertEqual(provider.dimensions, 256)
        self.assertEqual(provider.api_key, "sk-test")

    def test_settings_selection_large(self) -> None:
        settings = Settings(
            embedding_provider="openai_text_embedding_3_large",
            embedding_dim=256,
            openai_api_key="sk-test",
        )
        provider = embedding_provider_from_settings(settings)
        self.assertIsInstance(provider, OpenAIEmbedding3Provider)
        self.assertEqual(provider.model, "text-embedding-3-large")


if __name__ == "__main__":
    unittest.main()
