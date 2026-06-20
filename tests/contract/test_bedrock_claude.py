from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class BedrockClaudeContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.service = (ROOT / "apps/api/src/llm/bedrock-claude.service.ts").read_text(
            encoding="utf-8"
        )
        self.test = (ROOT / "apps/api/test/llm.e2e-spec.ts").read_text(encoding="utf-8")
        self.app_module = (ROOT / "apps/api/src/app.module.ts").read_text(encoding="utf-8")

    def test_bedrock_claude_provider_is_registered(self) -> None:
        self.assertIn("BedrockClaudeService", self.app_module)
        self.assertIn("BEDROCK_CLAUDE_RUNTIME_INVOKER", self.service)
        self.assertIn("bedrock_claude_client_not_configured", self.service)

    def test_final_answer_uses_sonnet_and_helper_tasks_use_haiku(self) -> None:
        for token in (
            'DEFAULT_BEDROCK_CLAUDE_SONNET_MODEL_ID = "anthropic.claude-sonnet-4-6"',
            'DEFAULT_BEDROCK_CLAUDE_HAIKU_MODEL_ID = "anthropic.claude-haiku-4-5-20251001-v1:0"',
            'task === "final_answer"',
            "BEDROCK_CLAUDE_SONNET_MODEL_ID",
            "BEDROCK_CLAUDE_HAIKU_MODEL_ID",
            "classification",
            "enrichment",
            "summarization",
            "high_risk_assistance",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.service)

    def test_bedrock_messages_payload_and_trace_contract_are_present(self) -> None:
        for token in (
            "invokeModel",
            "anthropic_version",
            'BEDROCK_CLAUDE_ANTHROPIC_VERSION = "bedrock-2023-05-31"',
            "messages",
            "max_tokens",
            "temperature",
            "input_tokens",
            "output_tokens",
            "latency_ms",
            "cost_record_id",
            "prompt_template_version",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.service)
        self.assertIn("uses Sonnet for final answers", self.test)
        self.assertIn("uses Haiku-class Claude", self.test)


if __name__ == "__main__":
    unittest.main()
