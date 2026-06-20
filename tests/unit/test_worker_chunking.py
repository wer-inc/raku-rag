from __future__ import annotations

import unittest

from workers.ingest.chunking import ChunkingConfig, TokenWindowChunker, table_chunks


class WorkerChunkingTest(unittest.TestCase):
    def test_defaults_target_250_to_400_with_max_450_tokens(self) -> None:
        config = ChunkingConfig()

        self.assertEqual(config.target_min_tokens, 250)
        self.assertEqual(config.target_max_tokens, 400)
        self.assertEqual(config.max_tokens, 450)

    def test_heading_path_and_metadata_are_separate_from_text(self) -> None:
        text = "# 点検\n\nポンプ P-12 を停止します。圧力を確認します。"
        chunks = TokenWindowChunker(ChunkingConfig(target_max_tokens=20, max_tokens=30)).chunk(
            text,
            metadata={"document_type": "manual"},
        )

        self.assertTrue(chunks)
        self.assertTrue(all(chunk.heading_path == ("点検",) for chunk in chunks))
        self.assertTrue(all("# 点検" not in chunk.text for chunk in chunks))
        self.assertEqual(chunks[0].metadata["document_type"], "manual")

    def test_table_summary_row_and_cell_chunks_are_emitted(self) -> None:
        chunks = table_chunks(
            headers=("equipment_id", "alarm_code"),
            rows=(("P-12", "E-152"),),
            heading_path=("設備一覧",),
            base_metadata={"sheet": "alarms"},
        )
        kinds = [chunk.metadata["chunk_kind"] for chunk in chunks]

        self.assertEqual(kinds, ["table_summary", "table_row", "table_cell", "table_cell"])
        self.assertEqual(chunks[0].heading_path, ("設備一覧",))
        self.assertIn("equipment_id", chunks[1].text)
        self.assertEqual(chunks[2].metadata["column"], "equipment_id")
        self.assertEqual(chunks[2].metadata["sheet"], "alarms")


if __name__ == "__main__":
    unittest.main()
