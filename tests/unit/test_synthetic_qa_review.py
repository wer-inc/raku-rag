import unittest

from raku_rag.domain.models import Chunk
from raku_rag.eval.synthetic_qa import (
    SyntheticQAReviewStatus,
    approve_synthetic_qa_item,
    generate_synthetic_qa_candidates,
    materialize_approved_eval_set,
    reject_synthetic_qa_item,
)


def _chunk(chunk_id: str, text: str, *, tombstone: bool = False) -> Chunk:
    return Chunk(
        tenant_id="tenant_a",
        collection_id="kb",
        document_id="doc_1",
        chunk_id=chunk_id,
        text=text,
        heading_path=("Work Instruction",),
        tombstone=tombstone,
    )


class TestSyntheticQAReviewWorkflow(unittest.TestCase):
    def test_generate_candidates_from_live_chunks_only(self) -> None:
        candidates = generate_synthetic_qa_candidates(
            [
                _chunk("c1", "Lock out and tag out the press before opening the safety guard."),
                _chunk("c2", "This deleted chunk must not become eval data.", tombstone=True),
            ]
        )

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].review_status, SyntheticQAReviewStatus.GENERATED)
        self.assertEqual(candidates[0].source_chunk_id, "c1")
        self.assertIn("Work Instruction", candidates[0].question)

    def test_unreviewed_candidates_cannot_gate_eval(self) -> None:
        candidate = generate_synthetic_qa_candidates(
            [_chunk("c1", "Approved inspection states that torque must be 42 Nm.")]
        )[0]

        with self.assertRaises(ValueError):
            candidate.to_eval_mapping()
        with self.assertRaises(ValueError):
            materialize_approved_eval_set(tenant_id="tenant_a", candidates=[candidate])

    def test_only_approved_candidates_materialize_into_eval_set(self) -> None:
        generated = generate_synthetic_qa_candidates(
            [
                _chunk("c1", "Approved instruction says verify zero energy before maintenance."),
                _chunk("c2", "Rejected candidate text should stay out."),
            ]
        )
        approved = approve_synthetic_qa_item(
            generated[0], reviewer_id="sme_1", review_note="good evidence"
        )
        rejected = reject_synthetic_qa_item(
            generated[1], reviewer_id="sme_1", review_note="too vague"
        )

        eval_set = materialize_approved_eval_set(
            tenant_id="tenant_a",
            candidates=[approved, rejected],
            eval_set_id="synthetic-approved",
        )

        self.assertEqual(eval_set.eval_set_id, "synthetic-approved")
        self.assertEqual(len(eval_set.items), 1)
        self.assertEqual(eval_set.items[0].expected_evidence[0].chunk_id, "c1")
        self.assertTrue(eval_set.dataset_version.startswith("dataset_"))

    def test_reviewer_id_is_required_for_review_decision(self) -> None:
        candidate = generate_synthetic_qa_candidates([_chunk("c1", "A short approved fact.")])[0]

        with self.assertRaises(ValueError):
            approve_synthetic_qa_item(candidate, reviewer_id="")
        with self.assertRaises(ValueError):
            reject_synthetic_qa_item(candidate, reviewer_id=" ")

    def test_round_trip_preserves_review_state(self) -> None:
        candidate = approve_synthetic_qa_item(
            generate_synthetic_qa_candidates(
                [_chunk("c1", "The checklist requires daily review.")]
            )[0],
            reviewer_id="sme_2",
        )

        restored = type(candidate).from_mapping(candidate.to_mapping())

        self.assertEqual(restored.review_status, SyntheticQAReviewStatus.APPROVED)
        self.assertEqual(restored.reviewer_id, "sme_2")
        self.assertEqual(restored.expected_evidence[0].document_id, "doc_1")


if __name__ == "__main__":
    unittest.main()
