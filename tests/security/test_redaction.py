"""T083 - redaction hardening coverage."""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stderr

from raku_rag.app import MvpSystem
from raku_rag.core.config import Settings, settings_from_env
from raku_rag.domain.models import ScopeType, SubjectType
from raku_rag.observability.audit import AuditEvent, InMemoryAuditSink
from raku_rag.observability.logging import log
from raku_rag.services.ingestion import IngestionService
from tests.helpers import claims, fresh

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
        sys.grant(T, ScopeType.COLLECTION, "manuals", SubjectType.USER, "alice")
        asset = sys.assets.get_visual_asset(claims(T, "alice"), result.asset.asset_id)
        visual_chunks = sys.store.visual_chunks_for_asset(T, result.asset.asset_id)

        self.assertNotIn("alice@example.com", result.regions[0].ocr_text)
        self.assertNotIn("sk-ABCDEFGHIJKLMNOP", result.regions[0].generated_caption_text)
        self.assertIn("[REDACTED:email]", result.regions[0].ocr_text)
        self.assertIn("[REDACTED:api_key]", result.regions[0].generated_caption_text)
        self.assertNotIn("GPSLatitude", result.asset.metadata["exif"])
        self.assertNotIn("bob@example.com", str(result.asset.metadata["exif"]))
        self.assertNotIn("alice@example.com", str(crop.metadata))
        self.assertNotIn("sk-ABCDEFGHIJKLMNOP", str(crop.metadata))
        self.assertTrue(result.regions[0].metadata["visual_region_redaction_required"])
        self.assertEqual(result.regions[0].metadata["visual_region_redaction_status"], "required")
        self.assertEqual(crop.redaction_policy_ref, "visual-region-redaction-required")
        self.assertTrue(crop.metadata["visual_region_redaction_required"])
        self.assertIn("email", crop.metadata["sensitive_detection_labels"])
        self.assertIn("api_key", crop.metadata["sensitive_detection_labels"])
        self.assertTrue(visual_chunks[0].metadata["visual_region_redaction_required"])
        self.assertIn("email", visual_chunks[0].metadata["sensitive_detection_labels"])
        self.assertIsNotNone(asset)
        assert asset is not None
        self.assertTrue(asset["regions"][0]["visual_region_redaction_required"])
        self.assertEqual(
            asset["crops"][0]["redaction_policy_ref"], "visual-region-redaction-required"
        )
        self.assertTrue(asset["regions"][0]["crop_uri"].startswith("memory://redacted-crops/"))
        self.assertTrue(asset["crops"][0]["crop_uri"].startswith("memory://redacted-crops/"))
        self.assertFalse(asset["crops"][0]["crop_uri"].startswith("memory://crops/"))
        self.assertNotIn("alice@example.com", str(asset))
        self.assertNotIn("sk-ABCDEFGHIJKLMNOP", str(asset))

    def test_text_ingestion_redacts_sensitive_values_before_indexing(self) -> None:
        sys = fresh()
        sys.ingest_text(
            tenant_id=T,
            collection_id="manuals",
            document_id="contact_doc",
            text=(
                "The support contact is alice@example.com and the integration key is "
                "sk-ABCDEFGHIJKLMNOP. Escalation goes to the blue desk."
            ),
        )
        sys.grant(T, ScopeType.COLLECTION, "manuals", SubjectType.USER, "alice")
        alice = claims(T, "alice")

        chunks = sys.search(alice, "support contact integration key", "manuals")
        indexed_text = "\n".join(item.chunk.text for item in chunks)
        self.assertNotIn("alice@example.com", indexed_text)
        self.assertNotIn("sk-ABCDEFGHIJKLMNOP", indexed_text)
        self.assertIn("[REDACTED:email]", indexed_text)
        self.assertIn("[REDACTED:api_key]", indexed_text)

        answer = sys.answer(alice, "what is the support contact?", "manuals")
        self.assertNotIn("alice@example.com", answer.text or "")
        self.assertNotIn("sk-ABCDEFGHIJKLMNOP", answer.text or "")
        doc = sys.registry.get(T, "contact_doc")
        self.assertTrue(doc.metadata["sensitive_detected"])
        self.assertTrue(doc.metadata["pii_redaction_applied"])
        self.assertTrue(doc.metadata["secret_redaction_applied"])
        self.assertEqual(doc.metadata["pii_redaction_mode"], "pre_index_redact")
        self.assertEqual(doc.metadata["pii_redaction_policy_ref"], "default-regex-v1")
        self.assertIn("email", doc.metadata["sensitive_detection_labels"])

    def test_text_ingestion_redacts_address_name_and_employee_identifier_patterns(self) -> None:
        sys = fresh()
        sys.ingest_text(
            tenant_id=T,
            collection_id="manuals",
            document_id="staff_doc",
            text=(
                "Contact Name: Alice Smith. Employee ID: OP-12345. "
                "Dispatch address is 123 Main Street. Postal code 100-0001."
            ),
        )
        sys.grant(T, ScopeType.COLLECTION, "manuals", SubjectType.USER, "alice")
        chunks = sys.search(claims(T, "alice"), "dispatch address employee", "manuals")
        indexed_text = "\n".join(item.chunk.text for item in chunks)

        self.assertNotIn("Alice Smith", indexed_text)
        self.assertNotIn("OP-12345", indexed_text)
        self.assertNotIn("123 Main Street", indexed_text)
        self.assertNotIn("100-0001", indexed_text)
        doc = sys.registry.get(T, "staff_doc")
        self.assertTrue(doc.metadata["pii_redaction_applied"])
        self.assertIn("name", doc.metadata["sensitive_detection_labels"])
        self.assertIn("employee_id", doc.metadata["sensitive_detection_labels"])
        self.assertIn("street_address", doc.metadata["sensitive_detection_labels"])
        self.assertIn("jp_postal_code", doc.metadata["sensitive_detection_labels"])

    def test_text_ingestion_detect_only_policy_tags_but_retains_indexed_text(self) -> None:
        sys = MvpSystem(Settings(pii_redaction_mode="detect_only"))
        sys.ingest_text(
            tenant_id=T,
            collection_id="manuals",
            document_id="contact_doc",
            text="The support contact is alice@example.com for urgent repairs.",
        )
        sys.grant(T, ScopeType.COLLECTION, "manuals", SubjectType.USER, "alice")
        chunks = sys.search(claims(T, "alice"), "support contact alice@example.com", "manuals")
        indexed_text = "\n".join(item.chunk.text for item in chunks)

        self.assertIn("alice@example.com", indexed_text)
        doc = sys.registry.get(T, "contact_doc")
        self.assertTrue(doc.metadata["sensitive_detected"])
        self.assertFalse(doc.metadata["pii_redaction_applied"])
        self.assertEqual(doc.metadata["pii_redaction_mode"], "detect_only")

    def test_text_ingestion_block_policy_fails_sensitive_documents(self) -> None:
        sys = MvpSystem(Settings(pii_redaction_mode="block"))

        job = sys.ingest_text(
            tenant_id=T,
            collection_id="manuals",
            document_id="contact_doc",
            text="The support contact is alice@example.com for urgent repairs.",
        )

        self.assertEqual(job.status, "failed")
        self.assertIn("redaction policy", job.failure_reason)
        self.assertIsNone(sys.registry.get(T, "contact_doc"))

    def test_redaction_policy_change_reindexes_same_raw_document(self) -> None:
        sys = MvpSystem(Settings(pii_redaction_mode="detect_only"))
        text = "The support contact is alice@example.com for urgent repairs."
        sys.ingest_text(
            tenant_id=T,
            collection_id="manuals",
            document_id="contact_doc",
            text=text,
        )
        self.assertEqual(sys.registry.get(T, "contact_doc").version, 1)

        sys.ingestion = IngestionService(
            sys.store,
            sys.embedder,
            sys.parser,
            sys.chunker,
            sys.registry,
            sys.metrics,
            sys.tracer,
            pii_redaction_mode="pre_index_redact",
        )
        sys.ingest_text(
            tenant_id=T,
            collection_id="manuals",
            document_id="contact_doc",
            text=text,
        )

        doc = sys.registry.get(T, "contact_doc")
        self.assertEqual(doc.version, 2)
        self.assertEqual(doc.metadata["pii_redaction_mode"], "pre_index_redact")
        sys.grant(T, ScopeType.COLLECTION, "manuals", SubjectType.USER, "alice")
        chunks = sys.search(claims(T, "alice"), "support contact", "manuals")
        indexed_text = "\n".join(item.chunk.text for item in chunks)
        self.assertNotIn("alice@example.com", indexed_text)
        self.assertIn("[REDACTED:email]", indexed_text)

    def test_redaction_policy_env_setting(self) -> None:
        settings = settings_from_env({"RAKU_PII_REDACTION_MODE": "block"})

        self.assertEqual(settings.pii_redaction_mode, "block")

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
