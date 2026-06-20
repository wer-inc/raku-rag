"""Smoke test for the stdlib local PoC UI (T072)."""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SERVER = ROOT / "poc-ui" / "server.py"


def load_server_module():
    spec = importlib.util.spec_from_file_location("poc_ui_server", SERVER)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load poc-ui/server.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PocUiSmokeTest(unittest.TestCase):
    def test_smoke_exercises_local_demo_paths(self) -> None:
        module = load_server_module()
        result = module.smoke()
        self.assertEqual(result["status"], "ok")
        self.assertIn("safety_block", result["checks"])


if __name__ == "__main__":
    unittest.main()
