from __future__ import annotations

import unittest

from raku_rag.core.query_planner import plan_query


class TestQueryPlanner(unittest.TestCase):
    def test_plans_high_risk_procedure_with_identifier_hints(self) -> None:
        plan = plan_query("受電盤MCC-3 420Vの感電防止LOTO手順を教えて")

        self.assertEqual(plan.intent, "safety_procedure")
        self.assertIn("safety_scope", plan.filter_hints)
        self.assertIn("document_kind", plan.filter_hints)
        self.assertTrue(plan.identifiers)
        self.assertGreater(len(plan.rewrite_hints), 0)

    def test_plans_troubleshooting_from_symptom_terms(self) -> None:
        plan = plan_query("搬送コンベヤの駆動ベアリングが異音と発熱で早期摩耗する原因と対策は？")

        self.assertEqual(plan.intent, "troubleshooting")
        self.assertIn("trouble_case", plan.filter_hints["document_kind"])

    def test_short_referential_question_asks_for_clarification(self) -> None:
        plan = plan_query("これはどうすればいい？")

        self.assertEqual(plan.intent, "clarification")
        self.assertFalse(plan.identifiers)


if __name__ == "__main__":
    unittest.main()
