from __future__ import annotations

import json
import unittest
from pathlib import Path

from raku_rag.observability.alerts import ALERT_RULES, alert_rule_names

ROOT = Path(__file__).resolve().parents[2]


class TestAlertRules(unittest.TestCase):
    def test_required_alerts_are_declared_in_code_and_ops_catalog(self) -> None:
        ops_catalog = json.loads((ROOT / "ops/alerts/rag-platform-alerts.json").read_text())
        ops_names = tuple(rule["name"] for rule in ops_catalog["rules"])
        expected = (
            "acl_post_check_diff",
            "deletion_reappearance",
            "budget_exceed",
            "failed_jobs",
            "quality_regression",
        )

        self.assertEqual(alert_rule_names(), expected)
        self.assertEqual(ops_names, expected)
        self.assertTrue(all(rule.severity in {"critical", "warning"} for rule in ALERT_RULES))
        self.assertTrue(all(rule.metric for rule in ALERT_RULES))


if __name__ == "__main__":
    unittest.main()
