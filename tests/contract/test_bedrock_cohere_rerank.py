from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class BedrockCohereRerankContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.service = (ROOT / "apps/api/src/rerank/bedrock-cohere-rerank.service.ts").read_text(
            encoding="utf-8"
        )
        self.test = (ROOT / "apps/api/test/rerank.e2e-spec.ts").read_text(encoding="utf-8")
        self.app_module = (ROOT / "apps/api/src/app.module.ts").read_text(encoding="utf-8")

    def test_bedrock_cohere_rerank_provider_is_registered(self) -> None:
        self.assertIn("BedrockCohereRerankService", self.app_module)
        self.assertIn("cohere.rerank-v3-5:0", self.service)
        self.assertIn("BEDROCK_RUNTIME_INVOKER", self.service)

    def test_bedrock_invoke_model_payload_matches_cohere_contract(self) -> None:
        for token in (
            "invokeModel",
            "modelId",
            'contentType: "application/json"',
            'accept: "*/*"',
            "documents",
            "api_version",
            "BEDROCK_COHERE_RERANK_API_VERSION = 2",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.service)

    def test_candidate_and_final_context_limits_are_guarded(self) -> None:
        for token in (
            "MIN_RERANK_CANDIDATE_LIMIT = 1",
            "MAX_RERANK_CANDIDATE_LIMIT = 80",
            "DEFAULT_RERANK_CANDIDATE_LIMIT = 20",
            "MIN_FINAL_CONTEXT_LIMIT = 5",
            "MAX_FINAL_CONTEXT_LIMIT = 12",
            "rerank_candidate_limit must be between 1 and 80",
            "final_context_limit must be between 5 and 12",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.service)

    def test_trace_records_latency_cost_and_skip_fallback(self) -> None:
        for token in (
            "latency_ms",
            "recordCost",
            "candidate_count",
            "final_context_count",
            "cost_record_id",
            'status: "succeeded" | "skipped"',
            "bedrock_client_not_configured",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.service)
        self.assertIn("skips rerank on Bedrock failure", self.test)
        self.assertIn("records score, latency, and cost trace", self.test)


if __name__ == "__main__":
    unittest.main()
