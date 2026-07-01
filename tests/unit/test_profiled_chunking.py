import unittest

from raku_rag.app import MvpSystem
from raku_rag.manufacturing.app import ManufacturingSystem
from raku_rag.manufacturing.domain.metadata import (
    DocumentKind,
    ManufacturingDocumentMetadata,
)
from raku_rag.providers.chunkers import ChunkingProfile, SentenceChunker


class TestProfiledChunking(unittest.TestCase):
    def test_document_kind_profile_adds_overlap(self) -> None:
        chunker = SentenceChunker(
            max_chars=200,
            profiles={
                "work_instruction": ChunkingProfile(
                    "work_instruction_test", max_chars=45, overlap_chars=15
                )
            },
        )
        text = "Step one isolate power. Step two lock the panel. Step three verify zero energy."

        chunks = chunker.chunk_document(text, metadata={"document_kind": "work_instruction"})

        self.assertGreaterEqual(len(chunks), 2)
        self.assertEqual(
            chunker.config_for_metadata({"document_kind": "work_instruction"})["chunking_profile"],
            "work_instruction_test",
        )
        self.assertTrue(chunks[1][0].startswith("isolate power."))
        self.assertLess(chunks[1][3][0], chunks[0][3][1])

    def test_default_chunk_method_keeps_existing_no_overlap_behavior(self) -> None:
        text = "# 点検手順\n\nポンプを停止します。圧力を確認します！再起動します？"
        chunks = SentenceChunker(max_chars=12).chunk(text)

        self.assertEqual(
            [chunk[0] for chunk in chunks],
            ["ポンプを停止します。", "圧力を確認します！", "再起動します？"],
        )

    def test_ingestion_records_chunking_profile_metadata(self) -> None:
        sys = MvpSystem()
        job = sys.ingest_text(
            tenant_id="tenant_a",
            collection_id="manuals",
            document_id="doc_1",
            text="# 点検手順\n\nApproved instruction says isolate energy before maintenance.",
            chunking_metadata={
                "document_kind": "work_instruction",
                "equipment_id": "EQ-1",
                "extra": {
                    "document_title": "Energy Isolation Work Instruction",
                    "source_sync_freshness": "curated_demo_seed",
                    "customer": "do-not-copy-sensitive-customer",
                },
            },
        )

        doc = sys.registry.get("tenant_a", "doc_1")
        stored_chunks = [
            chunk for chunk, _vec in sys.store.iter_items() if chunk.document_id == "doc_1"
        ]

        self.assertEqual(job.status, "succeeded")
        self.assertEqual(doc.metadata["chunking_profile"], "work_instruction_v1")
        self.assertTrue(stored_chunks)
        self.assertEqual(stored_chunks[0].metadata["chunking_profile"], "work_instruction_v1")
        self.assertEqual(stored_chunks[0].metadata["chunk_overlap_chars"], 80)
        self.assertEqual(
            stored_chunks[0].metadata["document_title"],
            "Energy Isolation Work Instruction",
        )
        self.assertEqual(stored_chunks[0].metadata["equipment_id"], "EQ-1")
        self.assertEqual(stored_chunks[0].metadata["section_path"], ["点検手順"])
        self.assertEqual(stored_chunks[0].metadata["source_sync_freshness"], "curated_demo_seed")
        self.assertNotIn("customer", stored_chunks[0].metadata)

    def test_manufacturing_metadata_drives_chunking_profile(self) -> None:
        sys = ManufacturingSystem()
        meta = ManufacturingDocumentMetadata(
            tenant_id="tenant_a",
            document_id="wi_1",
            document_kind=DocumentKind.WORK_INSTRUCTION,
        )

        sys.ingest_manufacturing(
            tenant_id="tenant_a",
            collection_id="manuals",
            document_id="wi_1",
            text="Approved work instruction says lock out the press before guard removal.",
            metadata=meta,
        )

        doc = sys._mvp.registry.get("tenant_a", "wi_1")

        self.assertEqual(doc.metadata["chunking_profile"], "work_instruction_v1")


if __name__ == "__main__":
    unittest.main()
