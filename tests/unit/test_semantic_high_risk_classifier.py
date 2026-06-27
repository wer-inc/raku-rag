from __future__ import annotations

import unittest

from raku_rag.core.config import Settings
from raku_rag.manufacturing.domain.safety import ClassificationSource
from raku_rag.manufacturing.safety.classifier import (
    LLMSemanticDangerClassifier,
    RuleHighRiskClassifier,
    semantic_danger_classifier_from_settings,
)


class _JsonLLM:
    def __init__(self, text: str) -> None:
        self.text = text
        self.prompts: list[str] = []

    def generate(self, prompt: str, context) -> str:
        self.prompts.append(prompt)
        return self.text


class TestProductionSemanticClassifier(unittest.TestCase):
    def test_semantic_high_risk_marks_danger(self) -> None:
        clf = RuleHighRiskClassifier(
            semantic_classifier=lambda query, meta, intent: {
                "is_high_risk": True,
                "confidence": 0.91,
                "reason_codes": ["semantic_machine_motion"],
            }
        )

        r = clf.classify("proceed with the covered procedure in the unusual condition", [])

        self.assertTrue(r.is_high_risk)
        self.assertEqual(r.classification_source, ClassificationSource.LLM)
        self.assertIn("semantic_machine_motion", r.reason_codes)

    def test_semantic_low_confidence_or_error_fails_safe(self) -> None:
        low = RuleHighRiskClassifier(
            semantic_classifier=lambda query, meta, intent: {
                "is_high_risk": False,
                "confidence": 0.5,
                "reason_codes": [],
            }
        )
        self.assertTrue(low.classify("proceed with the unusual condition", []).is_high_risk)

        def raising(query, meta, intent):
            raise RuntimeError("bedrock down")

        err = RuleHighRiskClassifier(semantic_classifier=raising)
        r = err.classify("proceed with the unusual condition", [])
        self.assertTrue(r.is_high_risk)
        self.assertIn("semantic_classifier_error", r.reason_codes)

    def test_semantic_confident_safe_can_clear_well_specified_query(self) -> None:
        clf = RuleHighRiskClassifier(
            semantic_classifier=lambda query, meta, intent: {
                "is_high_risk": False,
                "confidence": 0.93,
                "reason_codes": [],
            }
        )

        r = clf.classify("where is the approved calibration record stored", [])

        self.assertFalse(r.is_high_risk)
        self.assertEqual(r.classification_source, ClassificationSource.LLM)

    def test_llm_semantic_classifier_parses_json_and_factory_is_production_only(self) -> None:
        llm = _JsonLLM(
            '{"is_high_risk": true, "confidence": 0.95, "reason_codes": ["guard_bypass"]}'
        )
        semantic = LLMSemanticDangerClassifier(llm)
        result = semantic("should I proceed without the guard", [])

        self.assertEqual(result["reason_codes"], ["guard_bypass"])
        self.assertIn("Return ONLY JSON", llm.prompts[0])
        self.assertIsNone(semantic_danger_classifier_from_settings(Settings(), llm))
        self.assertIsNotNone(
            semantic_danger_classifier_from_settings(Settings(runtime_profile="production"), llm)
        )

    def test_factory_does_not_enable_json_semantic_classifier_for_extractive_llm(self) -> None:
        llm = _JsonLLM('{"is_high_risk": false, "confidence": 0.99, "reason_codes": []}')

        self.assertIsNone(
            semantic_danger_classifier_from_settings(
                Settings(runtime_profile="production", llm_provider="extractive"),
                llm,
            )
        )


if __name__ == "__main__":
    unittest.main()
