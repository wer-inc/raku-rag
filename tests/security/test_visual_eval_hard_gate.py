"""T079 - visual evaluation security checks are hard gates."""

from __future__ import annotations

import unittest

from raku_rag.domain.models import ScopeType, SubjectType
from raku_rag.eval import EvaluationRunner, EvaluationSet
from raku_rag.eval.runner import SECURITY_CHECKS
from tests.helpers import claims, fresh

T = "tenant_a"


class TestVisualEvaluationHardGate(unittest.TestCase):
    def setUp(self) -> None:
        self.sys = fresh()
        self.alice = claims(T, "alice")
        self.sys.grant(T, ScopeType.COLLECTION, "visual_manuals", SubjectType.USER, "alice")
        result = self.sys.ingest_visual_fixture(
            tenant_id=T,
            collection_id="visual_manuals",
            document_id="panel_image",
            image=b"OCR: Pump panel shows alarm AL-42.",
        )
        self.eval_set = EvaluationSet.register(
            tenant_id=T,
            items=[
                {
                    "question": "what alarm is shown?",
                    "expected_answer": "AL-42",
                    "expected_evidence": [
                        {
                            "kind": "visual",
                            "document_id": "panel_image",
                            "asset_id": result.asset.asset_id,
                            "region_id": result.regions[0].region_id,
                        }
                    ],
                }
            ],
        )

    def test_visual_security_violations_block_gate_result(self) -> None:
        visual_checks = (
            "visual_acl_leakage",
            "visual_deleted_reappearance",
            "visual_unauthorized_context",
            "visual_thumbnail_crop_leakage",
        )
        self.assertTrue(set(visual_checks).issubset(SECURITY_CHECKS))
        for check_name in visual_checks:
            with self.subTest(check_name=check_name):
                run = EvaluationRunner(self.sys).run(
                    self.eval_set,
                    principal=self.alice,
                    collection_id="visual_manuals",
                    security_check_counts={check_name: 1},
                )

                self.assertEqual(run.gate_result, "blocked")
                self.assertFalse(run.security_checks[check_name]["passed"])
                self.assertEqual(run.security_checks[check_name]["count"], 1)


if __name__ == "__main__":
    unittest.main()
