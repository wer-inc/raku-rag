"""Bedrock Claude answer LLM — invoker request/response shape and provider selection.

Uses an injected fake Bedrock client so no AWS credentials or boto3 network calls are touched.
"""

from __future__ import annotations

import io
import json
import unittest

from raku_rag.core.config import Settings
from raku_rag.domain.models import Chunk
from raku_rag.providers.llms import (
    BedrockClaudeLLMProvider,
    ExtractiveLLMProvider,
    build_bedrock_claude_invoker,
    llm_provider_from_settings,
)


class FakeBedrockClient:
    """Records invoke_model calls; returns a Bedrock Anthropic Messages-style body."""

    def __init__(self, text: str = "grounded answer.") -> None:
        self.text = text
        self.calls: list[dict] = []

    def invoke_model(self, *, modelId: str, body: bytes, accept: str, contentType: str) -> dict:
        self.calls.append({"modelId": modelId, "body": json.loads(body.decode("utf-8"))})
        payload = {"content": [{"type": "text", "text": self.text}], "stop_reason": "end_turn"}
        return {"body": io.BytesIO(json.dumps(payload).encode("utf-8"))}


def _chunk(text: str) -> Chunk:
    return Chunk(
        chunk_id="c1",
        tenant_id="demo",
        document_id="d1",
        collection_id="manuals",
        position=0,
        text=text,
    )


class TestBedrockClaudeInvoker(unittest.TestCase):
    def test_request_body_is_bedrock_messages_shape(self) -> None:
        client = FakeBedrockClient(text="トルクは 12N·m です。")
        invoker = build_bedrock_claude_invoker(region_name="ap-northeast-1", client=client)
        out = invoker(model_id="jp.anthropic.claude-sonnet-4-5", prompt="質問", max_tokens=512)
        self.assertEqual(out, "トルクは 12N·m です。")
        sent = client.calls[0]
        self.assertEqual(sent["modelId"], "jp.anthropic.claude-sonnet-4-5")
        self.assertEqual(sent["body"]["anthropic_version"], "bedrock-2023-05-31")
        self.assertEqual(sent["body"]["max_tokens"], 512)
        self.assertEqual(sent["body"]["messages"][0]["role"], "user")
        # No thinking / sampling params — those 400 on newer Bedrock Claude models.
        self.assertNotIn("temperature", sent["body"])
        self.assertNotIn("thinking", sent["body"])

    def test_provider_grounds_prompt_and_returns_text(self) -> None:
        client = FakeBedrockClient(text="ベアリングは 12N·m で固定。")
        provider = BedrockClaudeLLMProvider(
            model_id="m", invoker=build_bedrock_claude_invoker(client=client)
        )
        out = provider.generate("締め付けトルクは？", [_chunk("規定トルク 12N·m で固定する。")])
        self.assertEqual(out, "ベアリングは 12N·m で固定。")
        # The grounded prompt must carry the evidence text to the model.
        self.assertIn("12N·m", client.calls[0]["body"]["messages"][0]["content"])

    def test_provider_fails_closed_without_invoker(self) -> None:
        provider = BedrockClaudeLLMProvider(model_id="m", invoker=None)
        with self.assertRaises(RuntimeError):
            provider.generate("q", [_chunk("x")])

    def test_no_text_blocks_returns_empty(self) -> None:
        class NoText(FakeBedrockClient):
            def invoke_model(self, **kwargs):  # type: ignore[override]
                return {"body": io.BytesIO(json.dumps({"content": []}).encode("utf-8"))}

        invoker = build_bedrock_claude_invoker(client=NoText())
        self.assertEqual(invoker(model_id="m", prompt="q", max_tokens=8), "")


class TestLlmProviderSelection(unittest.TestCase):
    def test_default_is_extractive(self) -> None:
        self.assertIsInstance(llm_provider_from_settings(Settings()), ExtractiveLLMProvider)

    def test_llm_provider_bedrock_claude_selects_bedrock(self) -> None:
        settings = Settings(llm_provider="bedrock_claude", bedrock_claude_model_id="jp.anthropic.x")
        client = FakeBedrockClient()
        provider = llm_provider_from_settings(
            settings, invoker=build_bedrock_claude_invoker(client=client)
        )
        self.assertIsInstance(provider, BedrockClaudeLLMProvider)
        self.assertEqual(provider.model, "jp.anthropic.x")

    def test_llm_provider_extractive_override_beats_production_profile(self) -> None:
        settings = Settings(llm_provider="extractive", runtime_profile="production")

        provider = llm_provider_from_settings(settings)

        self.assertIsInstance(provider, ExtractiveLLMProvider)

    def test_llm_provider_override_beats_deterministic_profile(self) -> None:
        # llm_provider takes effect even when runtime_profile stays deterministic.
        settings = Settings(llm_provider="bedrock_claude", runtime_profile="deterministic")
        provider = llm_provider_from_settings(
            settings, invoker=build_bedrock_claude_invoker(client=FakeBedrockClient())
        )
        self.assertIsInstance(provider, BedrockClaudeLLMProvider)

    def test_production_profile_still_selects_bedrock(self) -> None:
        settings = Settings(runtime_profile="production")
        provider = llm_provider_from_settings(
            settings, invoker=build_bedrock_claude_invoker(client=FakeBedrockClient())
        )
        self.assertIsInstance(provider, BedrockClaudeLLMProvider)


if __name__ == "__main__":
    unittest.main()
