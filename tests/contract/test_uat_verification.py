from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class UatUsecaseVerificationContract(unittest.TestCase):
    def setUp(self) -> None:
        self.report = (ROOT / "docs" / "uat" / "usecase-verification.md").read_text(
            encoding="utf-8"
        )

    def test_report_tracks_every_uat_case_with_an_explicit_status(self) -> None:
        expected = (
            "X-01",
            "X-02",
            "X-03",
            "X-04",
            "MFG-01",
            "MFG-02",
            "MFG-03",
            "MFG-04",
            "MFG-05",
            "MFG-06",
            "MFG-07",
            "RE-01",
            "RE-02",
            "RE-03",
            "RE-04",
            "RE-05",
            "RE-06",
            "RE-07",
            "RE-08",
            "INV-01",
            "INV-02",
            "INV-03",
            "INV-04",
            "INV-05",
            "INV-06",
            "INV-07",
            "INV-08",
        )
        for case_id in expected:
            with self.subTest(case_id=case_id):
                self.assertRegex(
                    self.report,
                    rf"\| {re.escape(case_id)} \| (VERIFIED|VERIFIED-BEHAVIORAL) \|",
                )

    def test_report_claims_every_case_runtime_verified_and_none_not_executable(self) -> None:
        self.assertNotIn("| NOT EXECUTABLE |", self.report)
        self.assertIn("NOT EXECUTABLE cases: 0.", self.report)
        for prefix, total in (("X", 4), ("MFG", 7), ("RE", 8), ("INV", 8)):
            for n in range(1, total + 1):
                case_id = f"{prefix}-{n:02d}"
                with self.subTest(case_id=case_id):
                    self.assertRegex(
                        self.report,
                        rf"\| {re.escape(case_id)} \| (VERIFIED|VERIFIED-BEHAVIORAL) \|",
                    )

    def test_report_includes_command_evidence_and_summary_counts(self) -> None:
        for required in (
            "PYTHONPATH=src python -m unittest tests.uat.test_industry_usecases -v",
            "Ran 27 tests ... OK",
            "Full suite: GREEN",
            "Ran 566 tests ... OK (skipped=6)",
            "Use case verification: 27/27 runtime-verified.",
            "UAT-level executable verification",
        ):
            with self.subTest(required=required):
                self.assertIn(required, self.report)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
