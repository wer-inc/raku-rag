"""T023 — US1: grounded answer with citations + used_chunks + freshness."""

from __future__ import annotations

import unittest

from raku_rag.domain.models import ScopeType, SubjectType
from tests.helpers import claims, fresh

T = "tenant_a"


class TestAnswer(unittest.TestCase):
    def setUp(self) -> None:
        self.sys = fresh()
        self.sys.ingest_text(
            tenant_id=T,
            collection_id="c",
            document_id="d1",
            text="Backups run nightly at 02:00 UTC and are retained for thirty days.",
        )
        self.sys.grant(T, ScopeType.COLLECTION, "c", SubjectType.USER, "alice")
        self.alice = claims(T, "alice")

    def test_grounded_answer_with_traceable_citation(self) -> None:
        ans = self.sys.answer(self.alice, "when do backups run and how long are they retained?")
        self.assertEqual(ans.status, "ok")
        self.assertTrue(ans.text)
        self.assertTrue(ans.citations, "must return citations")
        self.assertTrue(ans.used_chunks, "must always return used_chunks")
        c = ans.citations[0]
        self.assertEqual(c.kind, "text")
        self.assertEqual(c.document_id, "d1")
        self.assertIsNotNone(c.chunk_id)
        self.assertIsNotNone(c.text_range)
        self.assertTrue(ans.freshness and ans.freshness[0].document_version >= 1)
        self.assertIn("text", ans.used_modalities)


if __name__ == "__main__":
    unittest.main()
