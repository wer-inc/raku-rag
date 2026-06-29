from __future__ import annotations

import unittest

from raku_rag.app import MvpSystem
from raku_rag.core.config import Settings
from raku_rag.domain.models import ScopeType, SubjectType
from raku_rag.manufacturing.domain.metadata import (
    ApprovalStatus,
    DocumentKind,
    ManufacturingDocumentMetadata,
)
from raku_rag.manufacturing.ingestion.metadata_enrichment import MFG_META_KEY
from raku_rag.manufacturing.wiring import build_manufacturing_answer_service
from tests.helpers import claims


class TestManufacturingAnswerExtractiveStaging(unittest.TestCase):
    def test_approved_ingested_text_answers_when_production_profile_uses_extractive_llm(
        self,
    ) -> None:
        settings = Settings(
            runtime_profile="production",
            llm_provider="extractive",
            allow_hashing_embeddings_in_production=True,
        )
        system = MvpSystem(settings=settings)
        marker = "STG-DEMO-QA27I-UNIT"
        document_id = "stg-demo-unit"
        text = (
            f"設備 {marker} の担当部門は保全計画チームです。"
            f"設備 {marker} の定期点検周期は 60 日です。"
        )
        job = system.ingest_text(
            tenant_id="demo",
            collection_id="manuals",
            source_id="stg-smoke-upload",
            document_id=document_id,
            text=text,
        )
        self.assertEqual(job.status, "succeeded")

        doc = system.registry.get("demo", document_id)
        self.assertIsNotNone(doc)
        doc.metadata[MFG_META_KEY] = ManufacturingDocumentMetadata(
            tenant_id="demo",
            document_id=document_id,
            approval_status=ApprovalStatus.APPROVED,
            effective_date="2024-01-10",
            document_kind=DocumentKind.WORK_INSTRUCTION,
        ).to_mapping()
        system.registry.put(doc)
        system.grant(
            "demo",
            ScopeType.COLLECTION,
            "manuals",
            SubjectType.USER,
            "sales-demo@example.com",
        )

        answer_service = build_manufacturing_answer_service(system)
        answer, classification, decision, _candidate_docs = answer_service.answer(
            claims("demo", "sales-demo@example.com"),
            f"{marker} の担当部門は?",
            system.profiles.resolve(None),
        )

        self.assertFalse(classification.is_high_risk)
        self.assertFalse(decision.blocked)
        self.assertEqual(answer.status, "ok")
        self.assertIn("保全計画", answer.text or "")
        self.assertTrue(answer.citations)
        self.assertEqual(answer.citations[0].approval_status, "approved")


if __name__ == "__main__":
    unittest.main()
