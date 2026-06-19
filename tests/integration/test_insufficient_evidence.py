"""T024 — US1: no evidence → insufficient_evidence (推測しない, FR-014/SC-002)."""
from __future__ import annotations

import unittest

from raku_rag.domain.models import ScopeType, SubjectType
from tests.helpers import claims, fresh

T = "tenant_a"


class TestInsufficientEvidence(unittest.TestCase):
    def setUp(self) -> None:
        self.sys = fresh()
        self.sys.ingest_text(
            tenant_id=T, collection_id="c", document_id="d1",
            text="The office cafeteria menu rotates weekly between four set lunches.",
        )
        self.sys.grant(T, ScopeType.COLLECTION, "c", SubjectType.USER, "alice")
        self.alice = claims(T, "alice")

    def test_unrelated_question_returns_insufficient(self) -> None:
        ans = self.sys.answer(self.alice, "describe the quantum cryptography key exchange protocol")
        self.assertEqual(ans.status, "insufficient_evidence")
        self.assertEqual(ans.used_chunks, ())
        self.assertEqual(ans.citations, ())
        self.assertIsNone(ans.text)


if __name__ == "__main__":
    unittest.main()
