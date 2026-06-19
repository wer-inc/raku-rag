"""T013 — US1 grounded manufacturing answer (quickstart S2; FR-MFG-005, [base:FR-012/013/014]).

Happy path: an APPROVED + effective manual answers a normal (non-high-risk) question with a grounded,
cited, traceable answer carrying the approval snapshot. This is the manufacturing analog of
tests/integration/test_answer.py, exercising the 001 answer path UNDER the safety overlay (the overlay
must not break the normal grounded-answer path — it only constrains high-risk answers).

TDD: RED now because ``raku_rag.manufacturing.app.ManufacturingSystem`` is unimplemented.
"""
from __future__ import annotations

import unittest

from raku_rag.domain.models import ScopeType, SubjectType
from tests.manufacturing.helpers import T, claims, fresh, mfg_meta


class TestGroundedManufacturingAnswer(unittest.TestCase):
    def setUp(self) -> None:
        self.sys = fresh()
        self.sys.ingest_manufacturing(
            tenant_id=T,
            collection_id="c",
            document_id="manual1",
            text="The conveyor motor lubrication interval is every ninety days under normal load.",
            metadata=mfg_meta(tenant_id=T, document_id="manual1"),
        )
        self.sys.grant(T, ScopeType.COLLECTION, "c", SubjectType.USER, "op")
        self.op = claims(T, "op")

    def test_approved_manual_normal_question_answers_with_approved_citation(self) -> None:
        ans = self.sys.answer(self.op, "what is the conveyor motor lubrication interval?")
        self.assertEqual(ans.status, "ok")
        self.assertTrue(ans.text)
        self.assertTrue(ans.citations, "must return citations")
        self.assertTrue(ans.used_chunks, "must always return used_chunks")
        # No safety block on a successful grounded answer.
        self.assertIsNone(ans.safety_block_reason)
        self.assertFalse(ans.obsolete_warning)
        # The cited evidence is the approved + effective manual (S2 expectation).
        c = ans.citations[0]
        self.assertEqual(c.document_id, "manual1")
        self.assertEqual(c.approval_status, "approved")
        self.assertEqual(c.effective_date, "2026-01-10")

    def test_used_chunks_trace_to_cited_document(self) -> None:
        ans = self.sys.answer(self.op, "what is the conveyor motor lubrication interval?")
        self.assertEqual(ans.status, "ok")
        # used_chunks references the chunk(s) that actually supported the answer (FR-012).
        self.assertTrue(set(ans.used_chunks))
        cited_chunk_ids = {c.chunk_id for c in ans.citations if c.chunk_id is not None}
        self.assertTrue(cited_chunk_ids & set(ans.used_chunks))


if __name__ == "__main__":
    unittest.main()
