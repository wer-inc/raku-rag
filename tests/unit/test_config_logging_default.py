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


if __name__ == "__main__":
    unittest.main()
