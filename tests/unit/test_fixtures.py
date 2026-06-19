"""P0-T21 — fixtures load deterministically and carry tenant scoping."""
from __future__ import annotations

import unittest

from tests.fixtures import PARSER_FIXTURES, load_json, load_text


class TestFixtures(unittest.TestCase):
    def test_parser_fixtures_present(self) -> None:
        for name in PARSER_FIXTURES:
            self.assertTrue(load_text("parser", name).strip(), name)

    def test_acl_and_eval_and_industry_fixtures(self) -> None:
        acl = load_json("acl", "grants.json")
        self.assertEqual(acl["tenant_id"], "tenant_local")
        self.assertTrue(acl["grants"])  # explicit grants only (deny-by-default)
        ev = load_json("eval", "eval_set.json")
        self.assertEqual(ev["tenant_id"], "tenant_local")
        self.assertTrue(any(i.get("expected_rejection") == "insufficient_evidence" for i in ev["items"]))
        ind = load_json("industry", "samples.json")
        self.assertIn("manufacturing", ind)
        self.assertIn("investment", ind)


if __name__ == "__main__":
    unittest.main()
