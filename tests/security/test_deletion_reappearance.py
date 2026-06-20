"""T037 — Security hard-gate: 削除済み文書が search/answer/citation/cache に再出現しない (SC-003)."""

from __future__ import annotations

import unittest

from raku_rag.domain.models import ScopeType, SubjectType
from tests.helpers import claims, fresh

T = "tenant_a"


class TestDeletionReappearance(unittest.TestCase):
    def setUp(self) -> None:
        self.sys = fresh()
        self.sys.ingest_text(
            tenant_id=T,
            collection_id="c",
            document_id="d1",
            text="The incident response runbook lists the on-call escalation path.",
        )
        self.sys.grant(T, ScopeType.COLLECTION, "c", SubjectType.USER, "alice")
        self.alice = claims(T, "alice")

    def test_answer_cites_then_deletion_removes(self) -> None:
        before = self.sys.answer(self.alice, "what is the on-call escalation path?")
        self.assertEqual(before.status, "ok")
        self.assertTrue(any(c.document_id == "d1" for c in before.citations))

        # seed a cache entry depending on d1 to prove invalidation
        self.sys.cache.put(T, "q:escalation", before, {"d1"})
        result = self.sys.deletion.delete(T, "d1")
        self.assertGreaterEqual(result.invalidated_cache_entries, 1)
        self.assertIsNone(self.sys.cache.get(T, "q:escalation"))

        after = self.sys.answer(self.alice, "what is the on-call escalation path?")
        self.assertEqual(after.status, "insufficient_evidence")
        self.assertEqual(after.used_chunks, ())

        results = self.sys.search(self.alice, "on-call escalation path")
        self.assertEqual(results, [], "deleted document must not reappear in search")


if __name__ == "__main__":
    unittest.main()
