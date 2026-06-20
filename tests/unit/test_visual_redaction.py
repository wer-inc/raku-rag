from __future__ import annotations

import unittest

from raku_rag.observability.redaction import Redactor


class TestVisualRedaction(unittest.TestCase):
    def test_visual_text_uses_existing_pii_secret_redaction(self) -> None:
        redactor = Redactor()

        text = redactor.redact_visual_text(
            "Caption says contact alice@example.com or key-abcdefghijkl"
        )

        self.assertNotIn("alice@example.com", text)
        self.assertNotIn("key-abcdefghijkl", text)
        self.assertIn("[REDACTED:email]", text)
        self.assertIn("[REDACTED:api_key]", text)

    def test_exif_high_risk_keys_are_stripped_by_default(self) -> None:
        redactor = Redactor()

        result = redactor.redact_exif(
            {
                "GPSLatitude": "35.0",
                "GPSLongitude": "139.0",
                "Make": "CameraCorp",
                "Model": "SensitiveModel",
                "DateTimeOriginal": "2026:06:20 12:00:00",
                "ImageDescription": "owner alice@example.com",
                "ColorSpace": "sRGB",
            }
        )

        self.assertEqual(
            set(result.removed_keys),
            {"GPSLatitude", "GPSLongitude", "Make", "Model", "DateTimeOriginal"},
        )
        self.assertNotIn("GPSLatitude", result.metadata)
        self.assertEqual(result.metadata["ColorSpace"], "sRGB")
        self.assertEqual(result.metadata["ImageDescription"], "owner [REDACTED:email]")


if __name__ == "__main__":
    unittest.main()
