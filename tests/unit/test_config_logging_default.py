"""P0-T11 — config default keeps raw retrieved context OFF (RT13 / OD-008 / ADR-015)."""

from __future__ import annotations

import unittest

from raku_rag.core.config import DEFAULT_SETTINGS, settings_from_env


class TestLoggingDefault(unittest.TestCase):
    def test_raw_context_disabled_by_default(self) -> None:
        self.assertEqual(DEFAULT_SETTINGS.logging_raw_retrieved_context_storage, "disabled")
        self.assertEqual(DEFAULT_SETTINGS.logging_raw_user_query_storage, "disabled")
        self.assertFalse(DEFAULT_SETTINGS.should_store_raw("raw_retrieved_context"))
        self.assertFalse(DEFAULT_SETTINGS.should_store_raw("raw_user_query"))

    def test_env_defaults_disabled_but_opt_in_possible(self) -> None:
        s = settings_from_env({})  # empty env
        self.assertFalse(s.should_store_raw("raw_retrieved_context"))
        opted = settings_from_env({"RAKU_LOG_RAW_RETRIEVED_CONTEXT": "full_opt_in"})
        self.assertTrue(opted.should_store_raw("raw_retrieved_context"))
        # user query still off unless separately opted in
        self.assertFalse(opted.should_store_raw("raw_user_query"))

    def test_performance_and_limit_knobs_are_configurable(self) -> None:
        s = settings_from_env(
            {
                "RAKU_MAX_DOCUMENT_BYTES": "1024",
                "RAKU_MAX_CHUNKS_PER_DOCUMENT": "12",
                "RAKU_MAX_CHUNK_CHARS": "80",
                "RAKU_MAX_CONCURRENT_QUERIES": "4",
                "RAKU_TARGET_P95_LATENCY_MS": "750",
                "RAKU_MAX_CONTEXT_TOKENS": "6000",
                "RAKU_MAX_CONTEXT_CHUNKS": "6",
                "RAKU_MAX_SYNCHRONOUS_LLM_CALLS": "1",
                "RAKU_TARGET_VISUAL_P95_LATENCY_MS": "1500",
                "RAKU_MIN_THROUGHPUT_QPS": "2.5",
            }
        )

        self.assertEqual(s.max_document_bytes, 1024)
        self.assertEqual(s.max_chunks_per_document, 12)
        self.assertEqual(s.max_chunk_chars, 80)
        self.assertEqual(s.max_concurrent_queries, 4)
        self.assertEqual(s.target_p95_latency_ms, 750.0)
        self.assertEqual(s.max_context_tokens, 6000)
        self.assertEqual(s.max_context_chunks, 6)
        self.assertEqual(s.max_synchronous_llm_calls, 1)
        self.assertEqual(s.target_visual_p95_latency_ms, 1500.0)
        self.assertEqual(s.min_throughput_qps, 2.5)


if __name__ == "__main__":
    unittest.main()
