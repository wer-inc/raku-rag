"""T083 - redaction hardening coverage."""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stderr

from raku_rag.observability.audit import AuditEvent, InMemoryAuditSink
from raku_rag.observability.logging import log
from tests.helpers import fresh

T = "tenant_a"


class TestRedactionHardening(unittest.TestCase):
    def test_structured_logs_and_audit_do_not_store_raw_secrets_or_pii(self) -> None:
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            log("test.event", note="email alice@example.com key sk-ABCDEFGHIJKLMNOP")

        line = stderr.getvalue()
        self.assertNotIn("alice@example.com", line)
        self.assertNotIn("sk-ABCDEFGHIJKLMNOP", line)
        self.assertIn("[REDACTED:email]", line)
        self.assertIn("[REDACTED:api_key]", line)

        sink = InMemoryAuditSink()
        event = sink.record(
            AuditEvent(
                tenant_id=T,
                correlation_id="trace_redaction",
                action="answer",
                decision="ok for alice@example.com",
                actor_id="alice",
                reason="token sk-ABCDEFGHIJKLMNOP",
                metadata={"caption": "contact bob@example.com", "count": 1},
            )
        )

        self.assertNotIn("alice@example.com", event.decision)
        self.assertNotIn("sk-ABCDEFGHIJKLMNOP", event.reason)
        self.assertEqual(event.metadata["caption"], "contact [REDACTED:email]")
        self.assertEqual(event.metadata["count"], 1)

    def test_visual_ocr_caption_exif_and_crop_metadata_do_not_expose_sensitive_values(self) -> None:
        sys = fresh()
        result = sys.ingest_visual_fixture(
            tenant_id=T,
            collection_id="manuals",
            document_id="visual_doc",
            image=b"OCR: Contact alice@example.com for panel access.\ncaption: key sk-ABCDEFGHIJKLMNOP",
            exif_metadata={
                "GPSLatitude": "35.0",
                "ImageDescription": "owner bob@example.com",
                "ColorSpace": "sRGB",
            },
        )
        crop = sys.crops.create_region_crop(result.regions[0])

        self.assertNotIn("alice@example.com", result.regions[0].ocr_text)
        self.assertNotIn("sk-ABCDEFGHIJKLMNOP", result.regions[0].generated_caption_text)
        self.assertIn("[REDACTED:email]", result.regions[0].ocr_text)
        self.assertIn("[REDACTED:api_key]", result.regions[0].generated_caption_text)
        self.assertNotIn("GPSLatitude", result.asset.metadata["exif"])
        self.assertNotIn("bob@example.com", str(result.asset.metadata["exif"]))
        self.assertNotIn("alice@example.com", str(crop.metadata))
        self.assertNotIn("sk-ABCDEFGHIJKLMNOP", str(crop.metadata))

    def test_eval_registration_redacts_queries_answers_and_visual_evidence_metadata(self) -> None:
        from raku_rag.eval import EvaluationSet

        eval_set = EvaluationSet.register(
            tenant_id=T,
            items=[
                {
                    "question": "Find contact alice@example.com with key sk-ABCDEFGHIJKLMNOP",
                    "expected_answer": "alice@example.com",
                    "expected_evidence": [
                        {
                            "kind": "visual",
                            "document_id": "visual_doc",
                            "asset_id": "asset_secret",
                            "region_id": "region_secret",
                        }
                    ],
                }
            ],
        )
        item = eval_set.items[0]

        self.assertNotIn("alice@example.com", item.question)
        self.assertNotIn("sk-ABCDEFGHIJKLMNOP", item.question)
        self.assertNotIn("alice@example.com", item.expected_answer)
        self.assertEqual(item.expected_evidence[0].asset_id, "asset_secret")


if __name__ == "__main__":
    unittest.main()
