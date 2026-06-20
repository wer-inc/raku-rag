"""T035 — US2: ingest text/markdown/html → indexed; unsupported → failed."""

from __future__ import annotations

import unittest

from tests.helpers import fresh

T = "tenant_a"


class TestIngest(unittest.TestCase):
    def setUp(self) -> None:
        self.sys = fresh()

    def test_text_markdown_html_indexed(self) -> None:
        for i, (ct, body) in enumerate(
            [
                ("text/plain", "Plain text policy document about access reviews."),
                ("text/markdown", "# Title\n\nMarkdown body about quarterly access reviews."),
                ("text/html", "<h1>Title</h1><p>HTML body about access reviews.</p>"),
            ]
        ):
            job = self.sys.ingestion.ingest(
                tenant_id=T,
                collection_id="c",
                source_id="s",
                document_id=f"d{i}",
                raw=body.encode(),
                content_type=ct,
            )
            self.assertEqual(job.status, "succeeded", f"{ct} failed: {job.failure_reason}")
            self.assertGreater(job.chunk_count, 0)

    def test_unsupported_content_type_failed_retryable(self) -> None:
        job = self.sys.ingestion.ingest(
            tenant_id=T,
            collection_id="c",
            source_id="s",
            document_id="dx",
            raw=b"\x00\x01",
            content_type="application/octet-stream",
        )
        self.assertEqual(job.status, "failed")
        self.assertTrue(job.failure_reason)


if __name__ == "__main__":
    unittest.main()
