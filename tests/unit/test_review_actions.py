"""ADR-018 §12.2 / §10.3 — reviewer actions on quarantined extraction chunks."""

from __future__ import annotations

import unittest

from raku_rag.app import MvpSystem
from raku_rag.domain.models import ScopeType, SubjectType
from raku_rag.services.ingestion_quality import (
    is_high_risk_citation_quality_eligible,
    is_retrieval_eligible,
)

T = "tenant_rev_actions"


class ReviewActionsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.m = MvpSystem()
        self.m.grant(T, ScopeType.COLLECTION, "c", SubjectType.USER, "alice")

    def _quarantine(self, document_id: str) -> str:
        self.m.ingest_text(
            tenant_id=T, collection_id="c", document_id=document_id, text="X " + "�" * 40
        )
        return next(
            r["chunk_id"]
            for r in self.m.list_extraction_reviews(T)
            if r["document_id"] == document_id
        )

    def _chunk(self, chunk_id: str):
        return next(c for c, _ in self.m.store.iter_items() if c.chunk_id == chunk_id)

    def test_approve_promotes_to_manual_approved_and_leaves_queue(self) -> None:
        cid = self._quarantine("d1")
        decision = self.m.apply_extraction_review_action(
            tenant_id=T, chunk_id=cid, action="approve", actor="reviewer1"
        )
        self.assertEqual(decision["status"], "manual_approved")
        self.assertTrue(decision["retrieval_eligible"])
        self.assertTrue(is_retrieval_eligible(self._chunk(cid).metadata))
        self.assertEqual(self._chunk(cid).metadata["reviewed_by"], "reviewer1")
        self.assertNotIn("d1", {r["document_id"] for r in self.m.list_extraction_reviews(T)})

    def test_reject_marks_rejected_and_stays_out_of_retrieval(self) -> None:
        cid = self._quarantine("d2")
        decision = self.m.apply_extraction_review_action(
            tenant_id=T, chunk_id=cid, action="reject", actor="r", reason="illegible"
        )
        self.assertEqual(decision["status"], "rejected")
        self.assertFalse(is_retrieval_eligible(self._chunk(cid).metadata))

    def test_edit_and_approve_replaces_text_and_reembeds(self) -> None:
        cid = self._quarantine("d3")
        decision = self.m.apply_extraction_review_action(
            tenant_id=T,
            chunk_id=cid,
            action="edit_and_approve",
            actor="r",
            corrected_text="Motor inspection every ninety days.",
        )
        self.assertEqual(decision["status"], "manual_approved")
        chunk = self._chunk(cid)
        self.assertEqual(chunk.text, "Motor inspection every ninety days.")
        self.assertTrue(is_retrieval_eligible(chunk.metadata))
        self.assertIn("original_text", chunk.metadata)

    def test_edit_and_approve_requires_corrected_text(self) -> None:
        cid = self._quarantine("d4")
        with self.assertRaises(ValueError):
            self.m.apply_extraction_review_action(
                tenant_id=T, chunk_id=cid, action="edit_and_approve", actor="r"
            )

    def test_mark_as_non_content_tombstones(self) -> None:
        cid = self._quarantine("d5")
        self.m.apply_extraction_review_action(
            tenant_id=T, chunk_id=cid, action="mark_as_non_content", actor="r"
        )
        chunk = self._chunk(cid)
        self.assertTrue(chunk.tombstone)
        self.assertEqual(chunk.metadata["extraction_quality_status"], "rejected")

    def test_escalate_and_reprocess_stay_in_queue(self) -> None:
        c_esc = self._quarantine("d6")
        c_rep = self._quarantine("d7")
        self.m.apply_extraction_review_action(
            tenant_id=T, chunk_id=c_esc, action="escalate", actor="r", reason="specialist"
        )
        self.m.apply_extraction_review_action(
            tenant_id=T, chunk_id=c_rep, action="reprocess", actor="r"
        )
        still = {r["document_id"] for r in self.m.list_extraction_reviews(T)}
        self.assertIn("d6", still)
        self.assertIn("d7", still)
        self.assertTrue(self._chunk(c_esc).metadata.get("review_escalated"))
        self.assertTrue(self._chunk(c_rep).metadata.get("reprocess_requested"))

    def test_text_review_item_becomes_high_risk_eligible_on_approve(self) -> None:
        cid = self._quarantine("d8")
        self.m.apply_extraction_review_action(
            tenant_id=T, chunk_id=cid, action="approve", actor="r"
        )
        self.assertTrue(is_high_risk_citation_quality_eligible(self._chunk(cid).metadata))

    def test_unknown_action_and_missing_chunk(self) -> None:
        cid = self._quarantine("d9")
        with self.assertRaises(ValueError):
            self.m.apply_extraction_review_action(
                tenant_id=T, chunk_id=cid, action="nope", actor="r"
            )
        with self.assertRaises(KeyError):
            self.m.apply_extraction_review_action(
                tenant_id=T, chunk_id="missing", action="approve", actor="r"
            )

    def test_audit_records_the_decision(self) -> None:
        cid = self._quarantine("d10")
        self.m.apply_extraction_review_action(
            tenant_id=T, chunk_id=cid, action="approve", actor="reviewer9"
        )
        actions = [e.action for e in self.m.audit.events(tenant_id=T)]
        self.assertIn("extraction_review.approve", actions)

    def test_reversed_decision_surfaces_as_a_review_overturn_in_metrics(self) -> None:
        # ADR-018 §18.2 review_overturn_rate, end-to-end through the real audit trail (not a fake).
        cid = self._quarantine("d11")
        self.m.apply_extraction_review_action(
            tenant_id=T, chunk_id=cid, action="approve", actor="reviewer1"
        )
        self.m.apply_extraction_review_action(
            tenant_id=T, chunk_id=cid, action="reject", actor="reviewer2", reason="re-review"
        )
        review = self.m.extraction_quality_metrics(T)["review"]
        self.assertEqual(review["reviewed_multiple_times"], 1)
        self.assertEqual(review["overturned"], 1)
        self.assertEqual(review["review_overturn_rate"], 1.0)


if __name__ == "__main__":
    unittest.main()
