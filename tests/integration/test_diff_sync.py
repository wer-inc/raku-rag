"""T038 — US2: diff-sync (checksum); 旧バージョンの内容が残らない (SC-007)."""
from __future__ import annotations

import unittest

from raku_rag.domain.models import ScopeType, SubjectType
from tests.helpers import claims, fresh

T = "tenant_a"


class TestDiffSync(unittest.TestCase):
    def setUp(self) -> None:
        self.sys = fresh()
        self.sys.grant(T, ScopeType.COLLECTION, "c", SubjectType.USER, "alice")
        self.alice = claims(T, "alice")

    def test_unchanged_content_is_skipped(self) -> None:
        text = "Quarterly revenue grew by twelve percent year over year."
        self.sys.ingest_text(tenant_id=T, collection_id="c", document_id="d1", text=text)
        job2 = self.sys.ingest_text(tenant_id=T, collection_id="c", document_id="d1", text=text)
        self.assertTrue(job2.skipped, "identical checksum should skip re-embedding")

    def test_updated_content_replaces_old_version(self) -> None:
        self.sys.ingest_text(
            tenant_id=T, collection_id="c", document_id="d1",
            text="The API rate limit is one hundred requests per minute.",
        )
        old = self.sys.answer(self.alice, "what is the API rate limit?")
        self.assertEqual(old.status, "ok")
        self.assertIn("hundred", old.text)

        # Source updated
        job = self.sys.ingest_text(
            tenant_id=T, collection_id="c", document_id="d1",
            text="The API rate limit is five hundred requests per minute now.",
        )
        self.assertFalse(job.skipped)
        doc = self.sys.registry.get(T, "d1")
        self.assertEqual(doc.version, 2)

        # Old content must not survive
        results = self.sys.search(self.alice, "one hundred requests per minute")
        for r in results:
            self.assertNotIn("one hundred requests per minute", r.chunk.text)


if __name__ == "__main__":
    unittest.main()
