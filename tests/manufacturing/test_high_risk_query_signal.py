"""`ManufacturingSystem.is_high_risk_query_signal` / `ManufacturingAnswerService.classify_query_signal`
— the retrieval-independent, CONCRETE high-risk pre-check on raw query text.

Introduced for the chatbot conversational-agent roadmap (originally P3). Its CURRENT consumer is L4
agentic control (`chatbot/agent.py`): every query an agentic decision-maker proposes is re-classified
by this signal before it is allowed to run a hop. (L2 coreference no longer uses it — L2's safety was
moved to the root-cause `DialogueContext.intent_query` threading; see `chatbot/coreference.py`'s
"Finding".)

Kept in its OWN file, not appended to `tests/manufacturing/test_safety_gate.py`, so this added
coverage does not modify an existing protected hard-gate file (gate.yml's "Verification/generation
separation" invariant, docs/loop-engineering.md §5).

The signal is deliberately NARROWER than plain `classifier.classify(...).is_high_risk` — see the
ambiguous-exclusion test below, which is the property this method exists to encode.
"""

from __future__ import annotations

import unittest

from raku_rag.manufacturing.domain.safety import ClassificationSource
from raku_rag.manufacturing.safety.classifier import RuleHighRiskClassifier
from tests.manufacturing.helpers import fresh


class TestHighRiskQuerySignal(unittest.TestCase):
    def test_concrete_intent_keyword_query_is_flagged(self) -> None:
        sys = fresh()
        self.assertTrue(
            sys.is_high_risk_query_signal(
                "How do I release the pressure in the hydraulic accumulator?"
            )
        )
        self.assertTrue(sys.is_high_risk_query_signal("その圧力の抜き方を教えて"))

    def test_benign_well_specified_query_is_not_flagged(self) -> None:
        sys = fresh()
        self.assertFalse(
            sys.is_high_risk_query_signal(
                "where is the employee cafeteria located inside building seven"
            )
        )

    def test_short_ambiguous_japanese_query_is_not_flagged_despite_the_classifier_failing_safe(
        self,
    ) -> None:
        # The critical distinction this method exists for: RuleHighRiskClassifier.classify(...) on a
        # bare, terse Japanese sentence fails safe to is_high_risk=True via the stage-3 "ambiguous"
        # catch-all (core.text.content_tokens cannot word-segment CJK text, so a whole short sentence
        # collapses to one "token", under the classifier's 3-token floor) -- correct for the FINAL
        # "may this answer assert" decision, but NOT itself evidence that THIS query text names a
        # concrete hazard. Treating the ambiguous fail-safe as a "this query is dangerous" signal here
        # would make L4 abort a hop for nearly every short Japanese query, with no safety benefit (the
        # real classifier + safety gate still run for real, unaffected, on whatever text reaches
        # `inner.answer(...)`).
        classifier = RuleHighRiskClassifier()
        premise = classifier.classify("その締付トルクは?", ())
        self.assertTrue(
            premise.is_high_risk, "premise: the raw classifier DOES fail safe to high_risk here"
        )
        self.assertEqual(premise.classification_source, ClassificationSource.RULE)

        sys = fresh()
        self.assertFalse(
            sys.is_high_risk_query_signal("その締付トルクは?"),
            "the concrete-signal pre-check must not treat the ambiguous fail-safe as a danger signal",
        )


if __name__ == "__main__":
    unittest.main()
