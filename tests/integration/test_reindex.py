"""T046 — reindex parallel build -> switch -> old version tombstone."""

from __future__ import annotations

import unittest

from raku_rag.domain.models import ScopeType, SubjectType
from raku_rag.services.structured_tables import STRUCTURED_TABLE_MANIFESTS_KEY
from tests.helpers import claims, fresh

T = "tenant_a"


class TestReindexService(unittest.TestCase):
    def setUp(self) -> None:
        self.sys = fresh()
        self.sys.grant(T, ScopeType.COLLECTION, "c", SubjectType.USER, "alice")
        self.alice = claims(T, "alice")

    def test_reindex_switches_to_new_version_and_tombstones_old_chunks(self) -> None:
        self.sys.ingest_text(
            tenant_id=T,
            collection_id="c",
            document_id="d1",
            text="The valve color for line A is red.",
        )

        plan = self.sys.reindex.reindex_documents(
            tenant_id=T,
            collection_id="c",
            source_id="manuals",
            documents={"d1": b"The valve color for line A is blue."},
            reason="embedding_model_change",
            created_by="ops",
        )

        self.assertEqual(plan.status, "succeeded")
        self.assertEqual(plan.affected_document_count, 1)
        self.assertEqual(plan.created_by, "ops")
        doc = self.sys.registry.get(T, "d1")
        self.assertEqual(doc.version, 2)
        self.assertFalse(doc.tombstone)

        answer = self.sys.answer(self.alice, "What color is the valve for line A?")
        self.assertEqual(answer.status, "ok")
        self.assertIn("blue", answer.text)
        self.assertTrue(all(c.version == 2 for c in answer.citations))

        old_results = self.sys.search(self.alice, "red valve line A")
        for result in old_results:
            self.assertNotIn("red", result.chunk.text.lower())

        if hasattr(self.sys.store, "_items"):
            old_chunk = self.sys.store._items["d1:0"][0]
            new_chunk = self.sys.store._items["d1:v2:0"][0]
            self.assertTrue(old_chunk.tombstone)
            self.assertFalse(new_chunk.tombstone)

    def test_reindex_reevaluates_quality_and_quarantines_broken_extraction(self) -> None:
        # ADR-018 A12 §Phase E: reprocessing a document whose extraction is now broken (mojibake)
        # must re-evaluate quality and quarantine it, not re-bless it as accepted.
        from raku_rag.services.ingestion_quality import (
            EXTRACTION_QUALITY_STATUS_KEY,
            QUALITY_STATUS_REVIEW_REQUIRED,
        )

        self.sys.ingest_text(
            tenant_id=T, collection_id="c", document_id="d1", text="Valve color line A is red."
        )
        plan = self.sys.reindex.reindex_documents(
            tenant_id=T,
            collection_id="c",
            source_id="manuals",
            documents={"d1": ("Valve color line A " + "�" * 40).encode("utf-8")},
            reason="reprocess",
            created_by="ops",
        )
        self.assertEqual(plan.status, "succeeded")

        primary_live = [
            c for c, _v in self.sys.store.iter_items() if c.document_id == "d1" and not c.tombstone
        ]
        self.assertEqual(primary_live, [])
        quarantined = [
            c
            for c, _v in self.sys.store.iter_quarantine_items()
            if c.document_id == "d1" and not c.tombstone
        ]
        self.assertTrue(quarantined)
        self.assertTrue(
            all(
                c.metadata[EXTRACTION_QUALITY_STATUS_KEY] == QUALITY_STATUS_REVIEW_REQUIRED
                for c in quarantined
            )
        )
        results = self.sys.search(self.alice, "valve color line A")
        self.assertNotIn("d1", {r.chunk.document_id for r in results})

    def test_failed_reindex_leaves_previous_version_live(self) -> None:
        self.sys.ingest_text(
            tenant_id=T,
            collection_id="c",
            document_id="d1",
            text="The release code is stable alpha.",
        )

        plan = self.sys.reindex.reindex_documents(
            tenant_id=T,
            collection_id="c",
            documents={"d1": b"The release code is beta."},
            content_type="application/pdf",
            reason="parser_version_change",
            created_by="ops",
        )

        self.assertEqual(plan.status, "failed")
        self.assertIn("unsupported content_type", plan.last_error)
        doc = self.sys.registry.get(T, "d1")
        self.assertEqual(doc.version, 1)

        answer = self.sys.answer(self.alice, "What is the release code?")
        self.assertEqual(answer.status, "ok")
        self.assertIn("alpha", answer.text)

    def test_reindex_preserves_structured_table_manifest(self) -> None:
        self.sys.ingestion.ingest(
            tenant_id=T,
            collection_id="metrics",
            source_id="quality-csv",
            document_id="defects",
            raw=b"month,defect count\nJan 2024,12\n",
            content_type="text/csv",
        )
        self.sys.grant(T, ScopeType.COLLECTION, "metrics", SubjectType.USER, "alice")

        plan = self.sys.reindex.reindex_documents(
            tenant_id=T,
            collection_id="metrics",
            source_id="quality-csv",
            documents={"defects": b"month,defect count\nJan 2024,12\nFeb 2024,18\n"},
            content_type="text/csv",
            reason="embedding_model_change",
            created_by="ops",
        )

        self.assertEqual(plan.status, "succeeded", plan.last_error)
        doc = self.sys.registry.get(T, "defects")
        self.assertEqual(doc.version, 2)
        self.assertEqual(len(doc.metadata[STRUCTURED_TABLE_MANIFESTS_KEY]), 1)

        answer = self.sys.answer(
            self.alice,
            "what is the total defect count by month?",
            collection_id="metrics",
        )

        self.assertEqual(answer.status, "ok")
        self.assertEqual(answer.route, "structured_tool")
        self.assertIn("Feb 2024=18", answer.text or "")
        self.assertEqual(answer.citations[0].kind, "spreadsheet")


if __name__ == "__main__":
    unittest.main()
