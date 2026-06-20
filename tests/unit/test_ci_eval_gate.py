from __future__ import annotations

import os
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


class TestCiEvalGate(unittest.TestCase):
    def test_ci_workflow_has_blocking_eval_gate(self) -> None:
        with open(os.path.join(ROOT, ".github", "workflows", "ci.yml"), encoding="utf-8") as fh:
            workflow = fh.read()

        self.assertIn("eval-gate:", workflow)
        self.assertIn("tests.integration.test_eval", workflow)
        self.assertIn("tests.integration.test_visual_eval", workflow)
        self.assertIn("tests.security.test_eval_hard_gate", workflow)
        self.assertIn("tests.security.test_visual_eval_hard_gate", workflow)
        self.assertIn("tests.unit.test_eval_baseline_gate", workflow)

    def test_gate_workflow_has_blocking_rt1_compose_smoke(self) -> None:
        with open(os.path.join(ROOT, ".github", "workflows", "gate.yml"), encoding="utf-8") as fh:
            workflow = fh.read()

        self.assertIn("rt1-compose:", workflow)
        self.assertIn("RT1 local dependency compose smoke", workflow)
        self.assertIn("workflow_dispatch:", workflow)
        self.assertIn("docker compose version", workflow)
        self.assertIn("bash scripts/docker-compose-smoke.sh", workflow)


if __name__ == "__main__":
    unittest.main()
