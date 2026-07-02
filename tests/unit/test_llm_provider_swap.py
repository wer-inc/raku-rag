"""LLM provider swap seam — OpenAI/Gemini adapters + factory selection (stdlib, injected HTTP)."""

from __future__ import annotations

import unittest
from dataclasses import replace

from raku_rag.core.config import Settings
from raku_rag.domain.models import Chunk
from raku_rag.providers.llms import (
    BedrockClaudeLLMProvider,
    ExtractiveLLMProvider,
    GeminiLLMProvider,
    OpenAIChatLLMProvider,
    llm_provider_from_settings,
)

CHUNK = Chunk(
    tenant_id="t",
    collection_id="c",
    document_id="d",
    chunk_id="d:0",
    text="耐圧試験は 0.60 MPa で 30 分保持します。",
)


class LLMProviderSwapTest(unittest.TestCase):
    def test_openai_adapter_calls_chat_completions(self) -> None:
        seen = {}

        def transport(url, headers, body, timeout):
            seen["url"] = url
            seen["auth"] = headers["authorization"]
            return {"choices": [{"message": {"content": "0.60 MPa で 30 分保持します。"}}]}

        provider = OpenAIChatLLMProvider(api_key="sk-test", transport=transport)
        text = provider.generate("試験圧力は？", [CHUNK])
        self.assertIn("0.60 MPa", text)
        self.assertTrue(seen["url"].endswith("/chat/completions"))
        self.assertEqual(seen["auth"], "Bearer sk-test")

    def test_gemini_adapter_calls_generate_content_with_header_key(self) -> None:
        seen = {}

        def transport(url, headers, body, timeout):
            seen["url"] = url
            seen["key_header"] = headers.get("x-goog-api-key")
            return {"candidates": [{"content": {"parts": [{"text": "30 分保持します。"}]}}]}

        provider = GeminiLLMProvider(api_key="g-test", transport=transport)
        text = provider.generate("保持時間は？", [CHUNK])
        self.assertIn("30 分", text)
        self.assertIn(":generateContent", seen["url"])
        self.assertNotIn("g-test", seen["url"])  # key travels as a header, never the URL
        self.assertEqual(seen["key_header"], "g-test")

    def test_adapters_fail_closed_without_keys(self) -> None:
        with self.assertRaises(RuntimeError):
            OpenAIChatLLMProvider(api_key="", transport=lambda *a: {}).generate("q", [CHUNK])
        with self.assertRaises(RuntimeError):
            GeminiLLMProvider(api_key="", transport=lambda *a: {}).generate("q", [CHUNK])

    def test_factory_selects_by_llm_provider_setting(self) -> None:
        base = Settings()
        cases = {
            "extractive": ExtractiveLLMProvider,
            "bedrock_claude": BedrockClaudeLLMProvider,
            "openai": OpenAIChatLLMProvider,
            "gemini": GeminiLLMProvider,
        }
        for name, cls in cases.items():
            with self.subTest(provider=name):
                provider = llm_provider_from_settings(replace(base, llm_provider=name))
                self.assertIsInstance(provider, cls)

    def test_factory_honors_model_overrides(self) -> None:
        s = replace(Settings(), llm_provider="gemini", gemini_llm_model="gemini-x")
        self.assertEqual(llm_provider_from_settings(s).model, "gemini-x")
        s = replace(Settings(), llm_provider="openai", openai_llm_model="gpt-x")
        self.assertEqual(llm_provider_from_settings(s).model, "gpt-x")


if __name__ == "__main__":
    unittest.main()
