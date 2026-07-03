"""★G3a Tier B — durable answer feedback over real Postgres (answer_feedback, 0023).

Skipped unless a Postgres with the 0023 migration applied is reachable (same conditional-skip
posture as test_query_trace_realpg). Verifies PostgresFeedbackRepository leaves durable,
RLS-isolated rows with PII-redacted comments, and that listing is newest-first per tenant.
"""

from __future__ import annotations

import os
import unittest

DSN = os.environ.get("POSTGRES_URL", "postgresql://raku:raku@127.0.0.1:5432/raku_parity")


def _answer_feedback_available() -> bool:
    try:
        import psycopg

        with psycopg.connect(DSN, connect_timeout=2) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM information_schema.tables WHERE table_name = 'answer_feedback'"
                )
                return cur.fetchone() is not None
    except Exception:
        return False


@unittest.skipUnless(
    _answer_feedback_available(),
    "Postgres with 0023_answer_feedback not reachable (Tier B / local-only)",
)
class TestAnswerFeedbackPersistenceRealPg(unittest.TestCase):
    def setUp(self) -> None:
        from raku_rag.persistence.feedback import PostgresFeedbackRepository
        from raku_rag.production import ProductionSystem

        self.sys = ProductionSystem(DSN, reset=True)
        self.addCleanup(self.sys.close)
        self.repo = PostgresFeedbackRepository(self.sys._conn)

    def _rows(self, tenant: str, sql: str, params: tuple) -> list:
        from raku_rag.persistence.postgres import _use_tenant

        _use_tenant(self.sys._conn, tenant)
        with self.sys._conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()

    def test_feedback_is_durable_categorized_and_redacted(self) -> None:
        created = self.repo.create(
            "tenant_a",
            actor_id="alice",
            answer_id="corr_1",
            score=2,
            comment="mail me at alice@example.com reason:wrong_evidence",
        )

        rows = self._rows(
            "tenant_a",
            "SELECT rating, score, reason_code, comment, actor_id, subject "
            "FROM answer_feedback WHERE correlation_id = %s",
            ("corr_1",),
        )
        self.assertEqual(len(rows), 1)
        rating, score, reason_code, comment, actor_id, subject = rows[0]
        self.assertEqual(rating, "down")
        self.assertEqual(score, 2)
        self.assertEqual(reason_code, "wrong_evidence")
        self.assertEqual(actor_id, "alice")
        self.assertEqual(subject, "user")
        # PII was redacted BEFORE the write; no raw email lands in the table.
        self.assertNotIn("alice@example.com", comment)
        self.assertIn("[REDACTED:email]", comment)

        listed = self.repo.list("tenant_a")
        self.assertEqual([row["feedback_id"] for row in listed], [created["feedback_id"]])
        self.assertEqual(listed[0]["answer_id"], "corr_1")

    def test_list_is_newest_first_and_rating_filterable(self) -> None:
        first = self.repo.create("tenant_a", actor_id="alice", answer_id="corr_1", score=5)
        second = self.repo.create("tenant_a", actor_id="alice", answer_id="corr_2", score=2)

        listed = self.repo.list("tenant_a")
        self.assertEqual(
            [row["feedback_id"] for row in listed],
            [second["feedback_id"], first["feedback_id"]],
        )
        downs = self.repo.list("tenant_a", rating_filter="down")
        self.assertEqual([row["feedback_id"] for row in downs], [second["feedback_id"]])

    def test_feedback_is_rls_isolated_per_tenant(self) -> None:
        created_a = self.repo.create("tenant_a", actor_id="alice", answer_id="corr_a", score=2)
        self.repo.create("tenant_b", actor_id="bob", answer_id="corr_b", score=2)

        # Under tenant_b's RLS context, tenant_a's feedback must be invisible even with a
        # deliberately-wrong WHERE (no tenant filter at all).
        visible_to_b = self._rows(
            "tenant_b",
            "SELECT tenant_id FROM answer_feedback WHERE feedback_id = %s",
            (created_a["feedback_id"],),
        )
        self.assertEqual(visible_to_b, [])
        all_b = self._rows("tenant_b", "SELECT DISTINCT tenant_id FROM answer_feedback", ())
        self.assertEqual(all_b, [("tenant_b",)])
        # The repository's own list API is equally scoped.
        self.assertEqual(
            [row["tenant_id"] for row in self.repo.list("tenant_b")],
            ["tenant_b"],
        )


if __name__ == "__main__":
    unittest.main()
