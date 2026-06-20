from __future__ import annotations

import unittest

from raku_rag.services.cost import CostService, VISUAL_COST_KINDS


class TestVisualCost(unittest.TestCase):
    def test_visual_cost_kinds_are_recorded_independently(self) -> None:
        cost = CostService()

        record = cost.record_visual_cost(
            "tenant_a",
            kind="vlm_image_tokens",
            amount=0.4,
            collection_id="manuals",
            job_id="job_visual",
            trace_id="trace_visual",
            quantity=128,
            unit="image_tokens",
            metadata={"model": "extractive-vlm-v1"},
        )

        self.assertIn("ocr_cost", VISUAL_COST_KINDS)
        self.assertIn("vlm_image_tokens", VISUAL_COST_KINDS)
        self.assertEqual(record.kind, "vlm_image_tokens")
        self.assertEqual(record.unit, "image_tokens")
        self.assertEqual(record.quantity, 128)
        self.assertEqual(record.metadata["model"], "extractive-vlm-v1")
        self.assertEqual(cost.records("tenant_a", kind="llm_completion_tokens"), ())
        self.assertEqual(cost.records("tenant_a", kind="vlm_image_tokens"), (record,))

    def test_unknown_visual_cost_kind_fails_closed(self) -> None:
        with self.assertRaises(ValueError):
            CostService().record_visual_cost("tenant_a", kind="llm_tokens", amount=1.0)


if __name__ == "__main__":
    unittest.main()
