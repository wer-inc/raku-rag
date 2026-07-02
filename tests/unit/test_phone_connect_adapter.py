"""L014 — Connect adapter pure logic: DID resolution, masking, response flattening (no network)."""

from __future__ import annotations

import importlib.util
import json
import os
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ADAPTER = ROOT / "infra/connect/lambda/connect_phone_adapter.py"
FIXTURES = json.loads((ROOT / "tests/fixtures/phone/connect_events.json").read_text("utf-8"))

DID_MAP = {
    "+815055550100": {
        "tenant_id": "demo",
        "user_id": "phone-gateway",
        "groups": ["phone_channel"],
        "collection_id": "manuals",
        "scenario_id": "faq-basic",
    }
}


def _load_adapter():
    spec = importlib.util.spec_from_file_location("connect_phone_adapter_unit", ADAPTER)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class ConnectAdapterUnitTest(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["RAKU_PHONE_DID_MAP"] = json.dumps(DID_MAP)
        os.environ["RAKU_INTERNAL_AUTH_SECRET"] = "unit-secret"  # pragma: allowlist secret
        self.adapter = _load_adapter()

    def tearDown(self) -> None:
        os.environ.pop("RAKU_PHONE_DID_MAP", None)
        os.environ.pop("RAKU_INTERNAL_AUTH_SECRET", None)

    def test_mask_phone_number_matches_platform_contract(self) -> None:
        self.assertEqual(self.adapter.mask_phone_number("+81300001234"), "+81******1234")
        self.assertEqual(self.adapter.mask_phone_number(""), "")
        self.assertEqual(self.adapter.mask_phone_number("12345"), "*****")

    def test_resolve_did_exact_and_domestic_format(self) -> None:
        self.assertIsNotNone(self.adapter.resolve_did("+815055550100"))
        # Domestic-format key lookup for the same subscriber number.
        os.environ["RAKU_PHONE_DID_MAP"] = json.dumps({"05055550100": DID_MAP["+815055550100"]})
        adapter = _load_adapter()
        self.assertIsNotNone(adapter.resolve_did("+815055550100"))
        self.assertIsNone(adapter.resolve_did("+815099999999"))

    def test_unknown_did_rejects_fail_closed(self) -> None:
        result = self.adapter.lambda_handler(FIXTURES["unknown_did"])
        self.assertEqual(result["action"], "reject")
        self.assertEqual(result["ok"], "false")
        self.assertTrue(result["speech_text"])

    def test_flatten_turn_maps_actions(self) -> None:
        flat = self.adapter._flatten_turn(
            {
                "ai_action": "handoff",
                "call_state": "handoff_pending",
                "speech_text": "担当者におつなぎします。",
                "handoff": {
                    "handoff_package_id": "handoff_1",
                    "reason": "customer_requested_human",
                    "destination_id": "general-support",
                },
            },
            "call_1",
        )
        self.assertEqual(flat["action"], "handoff")
        self.assertEqual(flat["handoff_reason"], "customer_requested_human")

        flat = self.adapter._flatten_turn(
            {"ai_action": "answer_with_citations", "call_state": "active", "speech_text": "はい。"},
            "call_1",
        )
        self.assertEqual(flat["action"], "continue")

        flat = self.adapter._flatten_turn(
            {"ai_action": "end_call", "call_state": "completed", "speech_text": ""}, "call_1"
        )
        self.assertEqual(flat["action"], "end_call")

    def test_flatten_values_are_strings(self) -> None:
        # Connect requires a flat string->string map from Lambda integrations.
        flat = self.adapter._flatten_turn(
            {"ai_action": None, "call_state": "active", "speech_text": None}, "call_1"
        )
        for key, value in flat.items():
            self.assertIsInstance(value, str, key)

    def test_turn_without_call_id_errors_without_silence(self) -> None:
        result = self.adapter.lambda_handler(FIXTURES["turn_faq"])
        self.assertEqual(result["action"], "error")
        self.assertTrue(result["speech_text"])

    def test_api_down_returns_spoken_error(self) -> None:
        os.environ["RAKU_INTERNAL_API_BASE"] = "http://127.0.0.1:1"  # closed port
        try:
            event = json.loads(json.dumps(FIXTURES["call_start"]))
            result = self.adapter.lambda_handler(event)
            self.assertEqual(result["action"], "error")
            self.assertTrue(result["speech_text"])  # never silent (SC-L3)
        finally:
            os.environ.pop("RAKU_INTERNAL_API_BASE", None)


if __name__ == "__main__":
    unittest.main()
