from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "scripts" / "demo" / "chatbot_golden_scenarios.py"
DATASET = ROOT / "scripts" / "demo" / "chatbot_golden_scenarios.json"


def _load_runner():
    spec = importlib.util.spec_from_file_location("chatbot_golden_scenarios", RUNNER)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class TestChatbotGoldenScenarios(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = _load_runner()
        self.dataset = json.loads(DATASET.read_text(encoding="utf-8"))

    def test_dataset_is_valid_and_representative(self) -> None:
        self.runner.validate_dataset(self.dataset)
        scenarios = self.dataset["scenarios"]
        self.assertGreaterEqual(len(scenarios), 16)
        categories = {scenario["category"] for scenario in scenarios}
        self.assertIn("grounded_lookup", categories)
        self.assertIn("approved_high_risk_procedure", categories)
        self.assertIn("troubleshooting", categories)
        self.assertIn("safety_refusal", categories)
        self.assertIn("security_refusal", categories)

    def test_policy_payload_matches_internal_collection_policy(self) -> None:
        policy_id, payload = self.runner.policy_payload("manuals", self.dataset)

        self.assertEqual(policy_id, "chat-internal:manuals")
        self.assertEqual(payload["source_id"], "")
        self.assertEqual(payload["collection_id"], "manuals")
        self.assertEqual(payload["exposure_mode"], "internal_authenticated")
        self.assertEqual(payload["allowed_channels"], ["web_chat"])
        self.assertEqual(payload["allowed_intents"], ["rag_question"])
        self.assertIs(payload["require_approved_effective"], True)
        self.assertIs(payload["allow_obsolete_primary_evidence"], False)

    def test_policy_payload_tracks_collection_override_for_default_policy_id(self) -> None:
        policy_id, payload = self.runner.policy_payload("faq", self.dataset)

        self.assertEqual(policy_id, "chat-internal:faq")
        self.assertEqual(payload["policy_id"], "chat-internal:faq")
        self.assertEqual(payload["collection_id"], "faq")

    def test_scenarios_with_defaults_applies_dataset_thresholds(self) -> None:
        dataset = {
            "default_min_answer_chars": 123,
            "default_min_citations": 2,
            "scenarios": [
                {
                    "id": "a",
                    "category": "grounded_lookup",
                    "question": "q",
                    "expected_behavior": "answer",
                    "required_citations": ["doc"],
                },
                {
                    "id": "b",
                    "category": "safety_refusal",
                    "question": "q",
                    "expected_behavior": "handoff",
                },
            ],
        }

        scenarios = self.runner.scenarios_with_defaults(dataset)

        self.assertEqual(scenarios[0]["min_answer_chars"], 123)
        self.assertEqual(scenarios[0]["min_citations"], 2)
        self.assertNotIn("min_answer_chars", scenarios[1])

    def test_answer_evaluator_catches_thin_answers(self) -> None:
        scenario = {
            "id": "thin",
            "category": "grounded_lookup",
            "expected_behavior": "answer",
            "required_citations": ["doc-a"],
            "required_terms": ["25", "95"],
            "min_answer_chars": 80,
        }
        response = {
            "assistant_message": {
                "ai_action": "answer_with_citations",
                "message": "25です。",
                "citations": [{"document_id": "doc-a"}],
            },
            "rag": {"answerable": True},
        }

        result = self.runner.evaluate_response(scenario, response)

        self.assertFalse(result.passed)
        self.assertTrue(any("answer too thin" in failure for failure in result.failures))
        self.assertTrue(any("95" in failure for failure in result.failures))

    def test_answer_evaluator_accepts_grounded_complete_answer(self) -> None:
        scenario = {
            "id": "complete",
            "category": "grounded_lookup",
            "expected_behavior": "answer",
            "required_citations": ["doc-a"],
            "required_terms": ["25", "95"],
            "min_answer_chars": 20,
        }
        response = {
            "assistant_message": {
                "ai_action": "answer_with_citations",
                "message": "M8は25 N.m、M16は95 N.mです。承認済み文書に基づきます。",
                "citations": [{"document_id": "doc-a"}],
            },
            "rag": {"answerable": True},
        }

        result = self.runner.evaluate_response(scenario, response)

        self.assertTrue(result.passed, msg=result.failures)

    def test_handoff_evaluator_accepts_safe_refusal(self) -> None:
        scenario = {
            "id": "refusal",
            "category": "safety_refusal",
            "expected_behavior": "handoff",
            "expected_no_answer_reasons": ["insufficient_evidence"],
        }
        response = {
            "assistant_message": {
                "ai_action": "handoff",
                "message": "承認済みの根拠だけでは回答を確定できません。",
                "citations": [],
            },
            "rag": {"answerable": False, "no_answer_reason": "insufficient_evidence"},
        }

        result = self.runner.evaluate_response(scenario, response)

        self.assertTrue(result.passed, msg=result.failures)


if __name__ == "__main__":
    unittest.main()
