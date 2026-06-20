"""T097 hard gate: Guardrails are defense-in-depth only.

The TypeScript adapter may call Bedrock Guardrails, but it must never become an authorization,
evidence, groundedness, or risk boundary. These checks keep that invariant in the Python gate.
"""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class GuardrailsAdapterHardGateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = (ROOT / "apps/api/src/guardrails/bedrock-guardrails.adapter.ts").read_text(
            encoding="utf-8"
        )
        self.test = (ROOT / "apps/api/test/guardrails.e2e-spec.ts").read_text(encoding="utf-8")

    def test_apply_guardrail_is_used_as_supplemental_input_output_filter(self) -> None:
        for token in (
            "applyGuardrail",
            "guardrailIdentifier",
            "guardrailVersion",
            "source: GuardrailSource",
            '"INPUT" | "OUTPUT"',
            "content",
            "GUARDRAIL_INTERVENED",
            "UNAVAILABLE",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.adapter)

    def test_guardrails_cannot_bypass_primary_controls(self) -> None:
        for token in (
            '"ACL"',
            '"RequiredEvidencePolicy"',
            '"GroundednessGate"',
            '"RiskGate"',
            "bypassCapabilities",
            "bypassesPrimaryControls(): false",
            "primaryControls.filter",
            "primaryBlocks.length === 0 && guardrail.allowed",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.adapter)

        self.assertIn("cannot bypass ACL", self.test)
        self.assertIn("RequiredEvidencePolicy", self.test)
        self.assertIn("GroundednessGate", self.test)
        self.assertIn("RiskGate", self.test)
        self.assertIn("missing Bedrock Guardrails as unavailable without widening", self.test)


if __name__ == "__main__":
    unittest.main()
