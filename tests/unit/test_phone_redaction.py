"""T009 — Phone transcript redaction (FR-034/043, SC-005)."""

from __future__ import annotations

import unittest

from raku_rag.phone.redaction import (
    RedactionResult,
    mask_phone_number,
    redact_text,
    transcript_redaction_status,
)


class TestPhoneNumberMasking(unittest.TestCase):
    def test_e164_keeps_prefix_and_last_four(self) -> None:
        self.assertEqual(mask_phone_number("+81300001234"), "+81******1234")

    def test_domestic_number_masked(self) -> None:
        masked = mask_phone_number("09012345678")
        self.assertTrue(masked.endswith("5678"))
        self.assertIn("******", masked)
        self.assertNotIn("0901234", masked)

    def test_empty_is_none(self) -> None:
        self.assertIsNone(mask_phone_number(""))
        self.assertIsNone(mask_phone_number(None))


class TestTranscriptRedaction(unittest.TestCase):
    def test_plain_jp_mobile_number_is_masked(self) -> None:
        result = redact_text("折り返しは09012345678までお願いします")
        self.assertNotIn("09012345678", result.text)
        self.assertTrue(result.flagged)
        self.assertIn("phone_number", result.classes)

    def test_card_like_number_is_redacted(self) -> None:
        result = redact_text("カード番号は 4111 1111 1111 1111 です")
        self.assertNotIn("4111 1111 1111 1111", result.text)
        self.assertTrue(result.flagged)

    def test_internal_auth_header_is_redacted(self) -> None:
        result = redact_text("X-Internal-Auth: super-secret-token-123")
        self.assertNotIn("super-secret-token-123", result.text)
        self.assertIn("internal_auth_header", result.classes)

    def test_bearer_token_is_redacted(self) -> None:
        # pragma comments must share the line with the fixture literal for detect-secrets.
        token_line = "認証は Bearer abcdef123456789 を使ってください"  # pragma: allowlist secret
        result = redact_text(token_line)
        self.assertNotIn("abcdef123456789", result.text)  # pragma: allowlist secret
        self.assertIn("bearer_token", result.classes)

    def test_api_key_is_redacted(self) -> None:
        result = redact_text("鍵は sk-abcdefghijklmnop です")
        self.assertNotIn("sk-abcdefghijklmnop", result.text)
        self.assertTrue(result.flagged)

    def test_email_is_redacted(self) -> None:
        result = redact_text("メールは taro@example.com です")
        self.assertNotIn("taro@example.com", result.text)
        self.assertTrue(result.flagged)

    def test_clean_text_is_unchanged(self) -> None:
        result = redact_text("営業時間を教えてください")
        self.assertEqual(result.text, "営業時間を教えてください")
        self.assertFalse(result.flagged)

    def test_empty_text(self) -> None:
        result = redact_text(None)
        self.assertEqual(result.text, "")
        self.assertFalse(result.flagged)


class TestRedactionStatusRollup(unittest.TestCase):
    def test_any_flag_marks_redacted(self) -> None:
        results = [
            RedactionResult(text="a", flagged=False, classes=()),
            RedactionResult(text="b", flagged=True, classes=("phone_number",)),
        ]
        self.assertEqual(transcript_redaction_status(results), "redacted")

    def test_clean_turns_not_needed(self) -> None:
        results = [RedactionResult(text="a", flagged=False, classes=())]
        self.assertEqual(transcript_redaction_status(results), "not_needed")


if __name__ == "__main__":
    unittest.main()
