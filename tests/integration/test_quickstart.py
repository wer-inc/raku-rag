"""T081 - quickstart S1-S10 verification script."""

from __future__ import annotations

import unittest

from raku_rag.domain.models import ScopeType, SubjectType
from raku_rag.eval import EvaluationRunner, EvaluationSet
from tests.helpers import claims, fresh

T = "tenant_a"


class TestQuickstartS1ToS10(unittest.TestCase):
    def test_quickstart_happy_path_security_eval_and_delete(self) -> None:
        sys = fresh()
        alice = claims(T, "alice")
        bob = claims(T, "bob")

        # S1: create a collection grant.
        sys.grant(T, ScopeType.COLLECTION, "manuals", SubjectType.USER, "alice")

        # S2: ingest a text document.
        text_job = sys.ingest_text(
            tenant_id=T,
            collection_id="manuals",
            document_id="backup_manual",
            text="Backups run nightly at 02:00 UTC and are retained for thirty days.",
        )
        self.assertEqual(text_job.status, "succeeded")

        # S3: search returns only authorized chunks.
        search = sys.search(alice, "when do backups run?", "manuals")
        self.assertTrue(search)
        self.assertEqual(search[0].chunk.document_id, "backup_manual")

        # S4: answer is grounded with citations.
        answer = sys.answer(alice, "when do backups run and how long are they retained?", "manuals")
        self.assertEqual(answer.status, "ok")
        self.assertTrue(answer.citations)
        self.assertEqual(answer.citations[0].kind, "text")

        # S5: unrelated questions fail closed.
        unrelated = sys.answer(alice, "what is the capital of an unrelated topic?", "manuals")
        self.assertEqual(unrelated.status, "insufficient_evidence")

        # S6: unauthorized users see no evidence.
        self.assertEqual(sys.search(bob, "backups", "manuals"), [])
        self.assertEqual(
            sys.answer(bob, "when do backups run?", "manuals").status, "insufficient_evidence"
        )

        # S7: ingest a visual fixture with OCR/caption.
        visual = sys.ingest_visual_fixture(
            tenant_id=T,
            collection_id="manuals",
            document_id="panel_image",
            image=b"OCR: Pump panel shows alarm AL-42.\ncaption: Pump alarm panel",
        )
        self.assertEqual(visual.caption_status, "succeeded")

        # S8: visual answer returns visual citation and authorized asset view.
        visual_answer = sys.answer(alice, "what alarm does the pump panel show?", "manuals")
        self.assertEqual(visual_answer.status, "ok")
        self.assertEqual(visual_answer.citations[0].kind, "visual")
        asset = sys.assets.get_visual_asset(alice, visual.asset.asset_id)
        self.assertIsNotNone(asset)

        # S9: eval smoke covers text and visual metrics.
        eval_set = EvaluationSet.register(
            tenant_id=T,
            items=[
                {
                    "question": "when do backups run?",
                    "expected_evidence": [{"document_id": "backup_manual"}],
                },
                {
                    "question": "what alarm does the pump panel show?",
                    "expected_evidence": [
                        {
                            "kind": "visual",
                            "document_id": "panel_image",
                            "asset_id": visual.asset.asset_id,
                            "region_id": visual.regions[0].region_id,
                        }
                    ],
                },
            ],
        )
        run = EvaluationRunner(sys).run(eval_set, principal=alice, collection_id="manuals")
        self.assertEqual(run.gate_result, "passed")
        self.assertEqual(run.metrics["recall_at_k"], 1.0)
        self.assertEqual(run.metrics["visual_recall_at_k"], 1.0)

        # S10: deletion tombstones evidence and invalidates retrieval/answer/asset paths.
        sys.deletion.delete(T, "panel_image")
        self.assertEqual(
            sys.answer(alice, "what alarm does the pump panel show?", "manuals").status,
            "insufficient_evidence",
        )
        self.assertIsNone(sys.assets.get_visual_asset(alice, visual.asset.asset_id))


if __name__ == "__main__":
    unittest.main()
