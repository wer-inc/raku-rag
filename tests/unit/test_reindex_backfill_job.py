from __future__ import annotations

import unittest

from raku_rag.dagster.jobs.reindex import build_reindex_backfill_request
from raku_rag.services.reindex import ReindexPlan


class ReindexBackfillJobTest(unittest.TestCase):
    def test_builds_dagster_compatible_backfill_request_from_plan(self) -> None:
        plan = ReindexPlan(
            reindex_plan_id="rp_1",
            tenant_id="tenant_a",
            collection_id="manuals",
            reason="embedding_model_change",
            target_embedding_model_version="embed-v2",
            scope={"document_ids": ["d1", "d2"]},
            affected_document_count=2,
            created_by="ops",
        )

        req = build_reindex_backfill_request(plan)

        self.assertEqual(req.reindex_plan_id, "rp_1")
        self.assertEqual(req.document_ids, ("d1", "d2"))
        self.assertEqual(req.target_embedding_model_version, "embed-v2")
        self.assertEqual(req.dagster_tags["tenant_id"], "tenant_a")
        self.assertEqual(req.dagster_tags["reindex_plan_id"], "rp_1")


if __name__ == "__main__":
    unittest.main()
