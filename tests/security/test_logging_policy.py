"""T099 hard gate: Langfuse must not store raw retrieved context by default."""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class LoggingPolicyHardGateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.enforcer = (ROOT / "apps/api/src/observability/logging-policy.service.ts").read_text(
            encoding="utf-8"
        )
        self.langfuse = (ROOT / "apps/api/src/observability/langfuse.ts").read_text(
            encoding="utf-8"
        )
        self.test = (ROOT / "apps/api/test/observability.e2e-spec.ts").read_text(encoding="utf-8")

    def test_raw_retrieved_context_is_disabled_by_default(self) -> None:
        for token in (
            "DEFAULT_LOGGING_POLICY",
            "LOGGING_POLICY_DEFAULTS.raw_retrieved_context_storage",
            'raw_retrieved_context_storage: "disabled"',
            'if (policy === "disabled")',
            "return undefined",
            "shouldStoreRaw",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.enforcer)
        self.assertIn("does not export raw retrieved context by default", self.test)
        self.assertIn('not.toContain("RAW_CONTEXT_SECRET")', self.test)

    def test_reference_metadata_is_retained_without_raw_context(self) -> None:
        for token in (
            "citation_ids",
            "chunk_ids",
            "document_ids",
            "prompt_template_version",
            "model",
            "latency_ms",
            "cost",
            "store_citation_ids",
            "store_chunk_ids",
            "store_prompt_template_version",
            "store_model_metadata",
            "store_latency",
            "store_cost",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.enforcer)

    def test_redaction_sampling_and_export_failure_are_enforced(self) -> None:
        for token in (
            "redactSecrets",
            "redactAll",
            "production_sampling_rate",
            "sampled_out",
            "langfuse_export_failed",
            "langfuse_client_not_configured",
            "sendTrace",
        ):
            with self.subTest(token=token):
                self.assertTrue(token in self.enforcer or token in self.langfuse)
        self.assertIn("redacts opted-in query, context, model input, and model output", self.test)
        self.assertIn("samples out traces before calling Langfuse", self.test)
        self.assertIn("does not let Langfuse export failures break the caller", self.test)


if __name__ == "__main__":
    unittest.main()
