"""★G3a — answer feedback persists via a repository (stdlib, in-memory).

Pins that `InMemoryFeedbackRepository` stores redacted, categorized rows newest-first with
tenant isolation, and that `_EvalFeedbackStore.create_feedback` keeps the existing
`{"feedback_id", "status": "accepted"}` response contract while delegating storage to the
repository seam (production swaps in PostgresFeedbackRepository over migration 0023).
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

from raku_rag.persistence.feedback import (
    InMemoryFeedbackRepository,
    build_feedback_record,
    rating_label,
)

ROOT = Path(__file__).resolve().parents[2]


def _load_answer_service():
    path = ROOT / "apps/answer-service/server.py"
    spec = importlib.util.spec_from_file_location("answer_service_server", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class TestFeedbackRecordNormalization(unittest.TestCase):
    def test_rating_label_maps_scores_to_taxonomy(self) -> None:
        self.assertEqual(rating_label(5), "up")
        self.assertEqual(rating_label(4), "up")
        self.assertEqual(rating_label(3), "neutral")
        self.assertEqual(rating_label(2), "down")
        self.assertEqual(rating_label(1), "down")
        self.assertEqual(rating_label(0), "neutral")

    def test_comment_is_pii_redacted_before_write(self) -> None:
        record = build_feedback_record(
            "tenant_a", actor_id="alice", score=2, comment="mail me at alice@example.com"
        )
        self.assertNotIn("alice@example.com", record["comment"])
        self.assertIn("[REDACTED:email]", record["comment"])

    def test_reason_and_citation_fall_back_to_comment_encoding(self) -> None:
        # Older web clients encode both inside the free-text comment.
        record = build_feedback_record(
            "tenant_a",
            actor_id="alice",
            score=2,
            comment="answer:needs_improvement reason:wrong_evidence",
        )
        self.assertEqual(record["reason_code"], "wrong_evidence")
        cited = build_feedback_record(
            "tenant_a",
            actor_id="alice",
            score=1,
            comment="citation:doc_1/chunk_2 verdict:incorrect",
        )
        self.assertEqual(cited["citation_id"], "doc_1/chunk_2")

    def test_explicit_fields_win_over_comment_parsing(self) -> None:
        record = build_feedback_record(
            "tenant_a",
            actor_id="alice",
            score=2,
            comment="reason:vague",
            reason_code="missing_doc",
            citation_id="doc_9",
        )
        self.assertEqual(record["reason_code"], "missing_doc")
        self.assertEqual(record["citation_id"], "doc_9")


class TestInMemoryFeedbackRepository(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = InMemoryFeedbackRepository()

    def test_list_is_newest_first_with_limit_offset_and_rating_filter(self) -> None:
        first = self.repo.create("tenant_a", actor_id="alice", answer_id="ans_1", score=5)
        second = self.repo.create("tenant_a", actor_id="alice", answer_id="ans_2", score=2)
        third = self.repo.create("tenant_a", actor_id="bob", answer_id="ans_3", score=2)

        listed = self.repo.list("tenant_a")
        self.assertEqual(
            [row["feedback_id"] for row in listed],
            [third["feedback_id"], second["feedback_id"], first["feedback_id"]],
        )

        downs = self.repo.list("tenant_a", rating_filter="down")
        self.assertEqual(
            [row["feedback_id"] for row in downs],
            [third["feedback_id"], second["feedback_id"]],
        )

        page = self.repo.list("tenant_a", limit=1, offset=1)
        self.assertEqual([row["feedback_id"] for row in page], [second["feedback_id"]])

    def test_list_is_tenant_isolated(self) -> None:
        self.repo.create("tenant_a", actor_id="alice", answer_id="ans_a", score=2)
        self.repo.create("tenant_b", actor_id="bob", answer_id="ans_b", score=2)
        self.assertEqual([r["tenant_id"] for r in self.repo.list("tenant_b")], ["tenant_b"])
        self.assertEqual(self.repo.list("tenant_other"), [])


class TestEvalFeedbackStoreContract(unittest.TestCase):
    def setUp(self) -> None:
        from raku_rag.app import MvpSystem

        self.srv = _load_answer_service()
        self.repo = InMemoryFeedbackRepository()
        self.store = self.srv._EvalFeedbackStore(MvpSystem(), feedback_repository=self.repo)

    def test_create_response_contract_is_unchanged(self) -> None:
        result = self.store.create_feedback(
            "tenant_a",
            {
                "answer_id": "ans_1",
                "subject": "user",
                "rating": 2,
                "comment": "answer:needs_improvement reason:vague",
            },
            "alice",
        )
        self.assertEqual(sorted(result), ["feedback_id", "status"])
        self.assertTrue(result["feedback_id"].startswith("fb_"))
        self.assertEqual(result["status"], "accepted")

    def test_created_feedback_is_listable_via_the_store(self) -> None:
        created = self.store.create_feedback(
            "tenant_a",
            {"answer_id": "ans_1", "subject": "user", "rating": 2, "reason_code": "vague"},
            "alice",
        )
        listed = self.store.list_feedback("tenant_a")
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["feedback_id"], created["feedback_id"])
        self.assertEqual(listed[0]["answer_id"], "ans_1")
        self.assertEqual(listed[0]["rating"], "down")
        self.assertEqual(listed[0]["reason_code"], "vague")
        self.assertEqual(listed[0]["actor_id"], "alice")
        # And the other tenant sees nothing.
        self.assertEqual(self.store.list_feedback("tenant_b"), [])

    def test_default_repository_is_in_memory(self) -> None:
        from raku_rag.app import MvpSystem

        store = self.srv._EvalFeedbackStore(MvpSystem())
        store.create_feedback("tenant_a", {"subject": "user", "rating": 5}, "alice")
        self.assertEqual(len(store.list_feedback("tenant_a")), 1)


if __name__ == "__main__":
    unittest.main()
