"""T079 - visual evaluation metrics."""

from __future__ import annotations

import unittest

from raku_rag.domain.models import ScopeType, SubjectType
from raku_rag.eval import EvaluationRunner, EvaluationSet
from tests.helpers import claims, fresh

T = "tenant_a"


class TestVisualEvaluationRunner(unittest.TestCase):
    def setUp(self) -> None:
        self.sys = fresh()
        self.alice = claims(T, "alice")
        self.sys.grant(T, ScopeType.COLLECTION, "manuals", SubjectType.USER, "alice")

    def test_visual_metrics_citation_bbox_latency_and_cost(self) -> None:
        result = self.sys.ingest_visual_fixture(
            tenant_id=T,
            collection_id="manuals",
            document_id="panel_image",
            image=b"OCR: Pump panel shows alarm AL-42.\ncaption: Pump alarm panel",
        )
        region = result.regions[0]
        eval_set = EvaluationSet.register(
            tenant_id=T,
            items=[
                {
                    "question": "what alarm does the pump panel show?",
                    "expected_answer": "AL-42",
                    "expected_evidence": [
                        {
                            "kind": "visual",
                            "document_id": "panel_image",
                            "asset_id": result.asset.asset_id,
                            "region_id": region.region_id,
                            "bbox": {
                                "x": region.bbox.x,
                                "y": region.bbox.y,
                                "width": region.bbox.width,
                                "height": region.bbox.height,
                            },
                        }
                    ],
                }
            ],
        )

        run = EvaluationRunner(self.sys).run(
            eval_set, principal=self.alice, collection_id="manuals"
        )

        self.assertEqual(run.gate_result, "passed")
        self.assertEqual(run.metrics["visual_recall_at_k"], 1.0)
        self.assertEqual(run.metrics["visual_citation_accuracy"], 1.0)
        self.assertAlmostEqual(run.metrics["bbox_iou"], 1.0)
        self.assertEqual(run.metrics["visual_groundedness"], 1.0)
        self.assertGreaterEqual(run.metrics["p95_visual_answer_latency_ms"], 0.0)
        self.assertGreater(run.metrics["visual_query_cost"], 0.0)
        self.assertEqual(run.examples[0].retrieved_asset_ids, (result.asset.asset_id,))
        self.assertEqual(run.examples[0].cited_region_ids, (region.region_id,))


if __name__ == "__main__":
    unittest.main()
