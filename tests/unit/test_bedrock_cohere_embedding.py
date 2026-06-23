from __future__ import annotations

import json
import unittest

from workers.ingest.providers.embeddings.bedrock_cohere import (
    CohereEmbedMultilingualV3Provider,
    RechunkRequired,
)


class _Body:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class _FakeBedrockRuntime:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def invoke_model(self, **kwargs):
        self.calls.append(kwargs)
        body = json.loads(kwargs["body"].decode("utf-8"))
        return {
            "body": _Body(
                {
                    "embeddings": [
                        {"float": [float(index == text_index) for index in range(1024)]}
                        for text_index, _text in enumerate(body["texts"])
                    ]
                }
            )
        }


class BedrockCohereEmbeddingTest(unittest.TestCase):
    def test_capability_and_bedrock_request_shape(self) -> None:
        client = _FakeBedrockRuntime()
        provider = CohereEmbedMultilingualV3Provider(client=client)

        vectors = provider.embed(["ポンプ P-12 の点検手順", "alarm E-152"])

        self.assertEqual(provider.dimensions, 1024)
        self.assertEqual(provider.max_input_tokens, 512)
        self.assertEqual(provider.capability.provider_family, "aws")
        self.assertTrue(provider.capability.zero_retention)
        self.assertEqual(len(vectors), 2)
        self.assertEqual(len(vectors[0]), 1024)
        self.assertEqual(client.calls[0]["modelId"], "cohere.embed-multilingual-v3")
        request = json.loads(client.calls[0]["body"].decode("utf-8"))
        self.assertEqual(request["input_type"], "search_document")
        self.assertEqual(request["embedding_types"], ["float"])

    def test_chunk_overflow_fails_closed_with_rechunk_plan(self) -> None:
        provider = CohereEmbedMultilingualV3Provider(
            client=_FakeBedrockRuntime(), max_input_tokens=10
        )

        with self.assertRaises(RechunkRequired) as ctx:
            provider.embed(["word " * 80])

        self.assertEqual(ctx.exception.plan.reason, "chunk_overflow_requires_rechunk")
        self.assertEqual(ctx.exception.plan.target_tokens, 350)
        self.assertEqual(ctx.exception.plan.max_tokens, 450)

    def test_malformed_embedding_payload_fails_closed(self) -> None:
        provider = CohereEmbedMultilingualV3Provider(client=_FakeBedrockRuntime())

        with self.assertRaisesRegex(ValueError, "embedding response item 0 is not a vector"):
            provider._parse_embeddings({"embeddings": [{"not_float": [1.0]}]})

        with self.assertRaisesRegex(ValueError, "embedding dimension mismatch"):
            provider._parse_embeddings({"embeddings": [{"float": [1.0]}]})


if __name__ == "__main__":
    unittest.main()
