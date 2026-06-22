"""T069 — focused unit tests for RuleHighRiskClassifier 3-stage cascade (FR-MFG-015).

Tests the classifier UNIT in isolation (no ManufacturingSystem wiring), covering each stage of the
metadata -> rule/keyword -> ambiguous-LLM cascade plus the fail-safe default and the attribution
fields (``reason_codes`` + ``classification_source``).

stdlib only; additive (new file). Behaviour verified against the live module before assertions were
written — a failure here would indicate a real regression, not a test that needs a src change.
"""

from __future__ import annotations

import unittest

from raku_rag.manufacturing.domain.metadata import ManufacturingDocumentMetadata
from raku_rag.manufacturing.domain.safety import ClassificationSource
from raku_rag.manufacturing.safety.classifier import RuleHighRiskClassifier


def _meta(**overrides) -> ManufacturingDocumentMetadata:
    base = dict(tenant_id="t", document_id="d")
    base.update(overrides)
    return ManufacturingDocumentMetadata(**base)


class _SafeLLM:
    """An LLM that confidently rules danger out (stage-3 'SAFE')."""

    def generate(self, prompt: str, context) -> str:  # noqa: D401 - test stub
        return "SAFE"


class _UnsureLLM:
    """An LLM that cannot confidently clear an ambiguous query."""

    def generate(self, prompt: str, context) -> str:
        return "UNSURE"


class _RaisingLLM:
    """An LLM provider that errors — must fail safe to high-risk."""

    def generate(self, prompt: str, context) -> str:
        raise RuntimeError("provider down")


class TestMetadataStage(unittest.TestCase):
    """(1) METADATA stage: a safety/quality/equipment classification tag => high-risk."""

    def setUp(self) -> None:
        self.clf = RuleHighRiskClassifier()
        # A clearly-benign, well-specified query so ONLY the metadata stage can fire.
        self.benign = "where is the employee cafeteria located inside building seven"

    def test_hazard_tag_marks_high_risk_with_metadata_source(self) -> None:
        r = self.clf.classify(self.benign, [_meta(hazard_tags=("感電",))])
        self.assertTrue(r.is_high_risk)
        self.assertEqual(r.classification_source, ClassificationSource.METADATA)
        self.assertIn("hazard_tag", r.reason_codes)

    def test_safety_category_field_marks_high_risk(self) -> None:
        r = self.clf.classify(self.benign, [_meta(safety_category="LOTO")])
        self.assertTrue(r.is_high_risk)
        self.assertEqual(r.classification_source, ClassificationSource.METADATA)
        self.assertIn("metadata:safety_category", r.reason_codes)

    def test_equipment_id_anchor_marks_high_risk(self) -> None:
        r = self.clf.classify(self.benign, [_meta(equipment_id="EQ-7")])
        self.assertTrue(r.is_high_risk)
        self.assertEqual(r.classification_source, ClassificationSource.METADATA)
        self.assertIn("metadata:equipment_id", r.reason_codes)

    def test_none_entries_in_candidate_metadata_are_skipped(self) -> None:
        # A None placeholder among the candidates must not crash the metadata survey.
        r = self.clf.classify(self.benign, [None, _meta(quality_category="judge")])  # type: ignore[list-item]
        self.assertTrue(r.is_high_risk)
        self.assertEqual(r.classification_source, ClassificationSource.METADATA)


class TestKeywordStage(unittest.TestCase):
    """(2) RULE + KEYWORD stage: dangerous-intent keywords (EN + JP)."""

    def setUp(self) -> None:
        self.clf = RuleHighRiskClassifier()

    def test_english_keyword_hit(self) -> None:
        r = self.clf.classify("how do I disassemble the gearbox assembly", [])
        self.assertTrue(r.is_high_risk)
        self.assertEqual(r.classification_source, ClassificationSource.KEYWORD)
        self.assertIn("disassembly", r.reason_codes)

    def test_japanese_keyword_hit(self) -> None:
        r = self.clf.classify("装置を停止する手順を教えてください", [])
        self.assertTrue(r.is_high_risk)
        self.assertEqual(r.classification_source, ClassificationSource.KEYWORD)
        self.assertIn("equipment_stop", r.reason_codes)

    def test_intent_hint_contributes_to_keyword_match(self) -> None:
        # The query alone is benign; the structured intent_hint carries the danger keyword.
        r = self.clf.classify(
            "proceed with the step", [], intent_hint="bypass the safety interlock"
        )
        self.assertTrue(r.is_high_risk)
        self.assertEqual(r.classification_source, ClassificationSource.KEYWORD)
        self.assertIn("safety_device", r.reason_codes)

    def test_metadata_takes_precedence_as_first_source_over_keyword(self) -> None:
        # Both metadata AND keyword fire; classification_source attributes the FIRST stage (metadata).
        r = self.clf.classify("disassemble the unit", [_meta(safety_category="x")])
        self.assertTrue(r.is_high_risk)
        self.assertEqual(r.classification_source, ClassificationSource.METADATA)
        # Both reason codes are still recorded.
        self.assertIn("metadata:safety_category", r.reason_codes)
        self.assertIn("disassembly", r.reason_codes)


class TestAmbiguousFailSafe(unittest.TestCase):
    """(3) AMBIGUOUS tie-break: terse/ambiguous => fail safe to high-risk ('迷えば high-risk')."""

    def test_terse_query_no_llm_fails_safe_with_rule_source(self) -> None:
        clf = RuleHighRiskClassifier()  # no LLM
        r = clf.classify("fix it", [])
        self.assertTrue(r.is_high_risk)
        self.assertEqual(r.reason_codes, ("ambiguous",))
        self.assertEqual(r.classification_source, ClassificationSource.RULE)

    def test_explicit_ambiguous_hint_fails_safe(self) -> None:
        clf = RuleHighRiskClassifier()
        r = clf.classify("the wider production matter here", [], intent_hint="ambiguous")
        self.assertTrue(r.is_high_risk)
        self.assertEqual(r.reason_codes, ("ambiguous",))

    def test_llm_cannot_clear_ambiguous_fails_safe_with_llm_source(self) -> None:
        clf = RuleHighRiskClassifier(llm=_UnsureLLM())
        r = clf.classify("look", [])
        self.assertTrue(r.is_high_risk)
        self.assertEqual(r.reason_codes, ("ambiguous",))
        self.assertEqual(r.classification_source, ClassificationSource.LLM)

    def test_llm_error_fails_safe(self) -> None:
        clf = RuleHighRiskClassifier(llm=_RaisingLLM())
        r = clf.classify("look", [])
        self.assertTrue(r.is_high_risk)
        self.assertEqual(r.classification_source, ClassificationSource.LLM)

    def test_llm_confidently_clears_ambiguous_query(self) -> None:
        # Only when the LLM is certain may an ambiguous query be ruled NOT high-risk.
        clf = RuleHighRiskClassifier(llm=_SafeLLM())
        r = clf.classify("look", [])
        self.assertFalse(r.is_high_risk)
        self.assertEqual(r.reason_codes, ())
        self.assertIsNone(r.classification_source)


class TestClearlyBenign(unittest.TestCase):
    """A non-dangerous, well-specified query => not high-risk, empty attribution."""

    def test_benign_query_not_high_risk(self) -> None:
        clf = RuleHighRiskClassifier()
        r = clf.classify("where is the employee cafeteria located inside building", [])
        self.assertFalse(r.is_high_risk)
        self.assertEqual(r.reason_codes, ())
        self.assertIsNone(r.classification_source)


class TestPhysicalInterventionKeywordRecall(unittest.TestCase):
    """GAP-S1: a LONGER (>=3 content tokens) keyword-free dangerous query must still fail safe.

    Before the physical_intervention reason code, these imperative hands-on / cover-bypass / manual
    machine-operation queries carried no labeled danger keyword AND were too long to trip the terse
    ambiguity branch, so they returned is_high_risk=False — the SafetyGate's approved-citation
    requirement (FR-MFG-005/SC-MFG-006) then never fired. They must classify high-risk (FR-MFG-015
    「迷えば high-risk」). Precision negative controls confirm informational queries stay non-high-risk.
    """

    def setUp(self) -> None:
        self.clf = RuleHighRiskClassifier()

    def test_keyword_free_dangerous_queries_fail_safe_to_high_risk(self) -> None:
        dangerous = (
            "open the inner housing then proceed",
            "reach into the moving rollers and clear the blockage by hand",
            "override the controller and run the cycle without the cover",
            "cut the locked wire and restart the cycle manually",
            "neutralize the acid spill by wiping the solvent residue by hand",
            "非常停止を解除してガードを外したまま手動で再起動する方法",
        )
        for q in dangerous:
            with self.subTest(query=q):
                r = self.clf.classify(q, [])
                self.assertTrue(
                    r.is_high_risk,
                    f"a keyword-free physical-intervention query must fail safe to high-risk: {q!r}",
                )
                self.assertIn("physical_intervention", r.reason_codes)
                self.assertEqual(r.classification_source, ClassificationSource.KEYWORD)

    def test_adversarial_danger_categories_trigger_expected_reason_codes(self) -> None:
        dangerous = (
            (
                "open the energized electrical panel and inspect the live wire",
                "electric_shock",
            ),
            (
                "lift the press die with the crane while a worker reaches underneath",
                "heavy_object",
            ),
            (
                "非常停止を解除してガードを外したまま手動で再起動する方法",
                "safety_device",
            ),
        )
        for q, expected_reason in dangerous:
            with self.subTest(query=q):
                r = self.clf.classify(q, [])
                self.assertTrue(r.is_high_risk)
                self.assertIn(expected_reason, r.reason_codes)
                self.assertEqual(r.classification_source, ClassificationSource.KEYWORD)

    def test_informational_queries_stay_non_high_risk(self) -> None:
        # Precision negative control: longer benign informational/locational queries must NOT trip the
        # new reason code (otherwise the approved-citation gate would over-fire on benign questions).
        benign = (
            "where is the employee cafeteria located inside building seven",
            "what is the effective date of the approved torque specification manual",
            "who approved the latest revision of the assembly work instruction",
            "what alarm does the pump panel show on the operator screen",
            "where is the operator panel drawing stored for line seven",
            "show the electrical cabinet maintenance calendar",
        )
        for q in benign:
            with self.subTest(query=q):
                r = self.clf.classify(q, [])
                self.assertFalse(
                    r.is_high_risk, f"a benign informational query must stay non-high-risk: {q!r}"
                )


if __name__ == "__main__":
    unittest.main()
